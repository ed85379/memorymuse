
import os
from datetime import datetime
import openai
import base64
from pathlib import Path
from typing import Literal, IO
from contextlib import ExitStack
from app.core.assets_core import (
    AssetLifecycle,
    AssetProvenance,
    create_local_asset_from_bytes,
    create_local_asset_from_base64,
    create_local_asset_from_url,
    asset_doc_to_ref,
    get_asset_full_path,
    asset_to_data_url,
)
from app.config import muse_settings

openai.api_key = muse_settings.get_section("llm_config").get("OPENAI_API_KEY")
MUSE_NAME = muse_settings.get_section('muse_config').get('MUSE_NAME')
client = openai.OpenAI()


ImageOutputFormat = Literal["png", "jpeg", "webp"]
ImageQuality = Literal["low", "medium", "high", "auto"]
ImageModeration = Literal["auto", "low"]
ImageSize = Literal["1024x1024", "1536x1024", "1024x1536", "auto"]
InputFidelity = Literal["high", "low"]
ImageSources = IO[bytes]

SUPPORTED_OPENAI_SOURCE_MIMETYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
}

SUPPORTED_OPENAI_SOURCE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

OPENAI_IMAGE_SOURCE_LIMIT = 16

def get_openai_image_config() -> dict:
    image_config = muse_settings.get_section("openai_image_generation") or {}

    return {
        "generate_model": image_config.get("OPENAI_GENERATE_IMAGE_MODEL", "gpt-image-2"),
        "muse_model": image_config.get("OPENAI_MUSE_IMAGE_MODEL", "gpt-image-2"),
        "default_image_size": image_config.get("OPENAI_IMAGE_SIZE", "auto"),
        "default_output_format": image_config.get("OPENAI_IMAGE_OUTPUT_FORMAT", "png"),
        "default_quality": image_config.get("OPENAI_IMAGE_QUALITY", "medium"),
        "default_moderation": image_config.get("OPENAI_IMAGE_MODERATION", "low"),
        "default_input_fidelity": image_config.get("OPENAI_IMAGE_INPUT_FIDELITY", "high"),
        "muse_source_url": image_config.get(
            "OPENAI_MUSE_SOURCE_URL",
            "http://localhost:8080/iris-new.jpg",
        ),
    }

def openai_supports_moderation_on_generate(model: str) -> bool:
    # Observed/docs: moderation belongs to generation path for GPT image models.
    # Do not pass moderation to edit.
    return model.startswith("gpt-image")


def openai_supports_input_fidelity_on_edit(model: str) -> bool:
    # Docs have been inconsistent here. Live observed behavior:
    # gpt-image-2 rejects input_fidelity.
    #
    # Keep this conservative. Expand only after live testing.
    return model in {
        "gpt-image-1",
        "gpt-image-1.5",
    }

def validate_openai_source_asset(asset_doc: dict) -> Path:
    mimetype = (asset_doc.get("mimetype") or "").lower()

    if mimetype not in SUPPORTED_OPENAI_SOURCE_MIMETYPES:
        raise ValueError(
            f"Unsupported OpenAI source image mimetype: {mimetype}. "
            "Supported types are image/jpeg, image/png, and image/webp."
        )

    path = Path(get_asset_full_path(asset_doc))

    if not path.exists():
        raise FileNotFoundError(
            f"Source image asset file does not exist: {asset_doc.get('_id')}"
        )

    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_OPENAI_SOURCE_SUFFIXES:
        raise ValueError(
            f"Unsupported OpenAI source image extension: {suffix}. "
            "Supported extensions are .jpg, .jpeg, .png, and .webp."
        )

    size_bytes = path.stat().st_size
    max_bytes = 50 * 1024 * 1024

    if size_bytes > max_bytes:
        raise ValueError(
            f"OpenAI source image is too large: {size_bytes} bytes. "
            "Maximum supported size is 50MB."
        )

    return path

def normalize_image_sources(sources=None) -> list[dict]:
    normalized_sources = []

    for source in sources or []:
        if not isinstance(source, dict):
            raise ValueError("Each source must be an object.")

        source_type = source.get("type")
        if source_type != "url":
            raise ValueError("generate_image currently supports only source type 'url'.")

        url = source.get("url")
        if not url or not isinstance(url, str):
            raise ValueError("URL source missing valid 'url' field.")

        normalized_sources.append({
            "type": "url",
            "url": url,
        })

    if len(normalized_sources) > OPENAI_IMAGE_SOURCE_LIMIT:
        raise ValueError(
            f"generate_image supports at most {OPENAI_IMAGE_SOURCE_LIMIT} source images."
        )

    return normalized_sources

def _run_openai_image_tool(
    *,
    prompt: str,
    image_size: ImageSize,
    sources: list[dict] | None,
    project_id: str | None,
    model: str,
    source_tool: str,
    moderation: ImageModeration = "low",
    n: int = 1,
    output_format: ImageOutputFormat = "png",
    quality: ImageQuality = "medium",
    input_fidelity: InputFidelity = "high",
):
    normalized_sources = normalize_image_sources(sources)

    if not isinstance(n, int) or not (1 <= n <= 10):
        raise ValueError("OpenAI image generation supports n between 1 and 10.")

    image_assets = [
        create_local_asset_from_url(
            url=source["url"],
            source_type="image_source",
        )
        for source in normalized_sources
    ]

    is_edit = bool(image_assets)
    operation = "edit" if is_edit else "generate"

    if is_edit:
        with ExitStack() as stack:
            image_files = [
                stack.enter_context(open(validate_openai_source_asset(asset), "rb"))
                for asset in image_assets
            ]

            edit_kwargs = {
                "model": model,
                "image": image_files,
                "prompt": prompt,
                "size": image_size,
                "n": n,
                "output_format": output_format,
                "quality": quality,
            }

            if openai_supports_input_fidelity_on_edit(model):
                edit_kwargs["input_fidelity"] = input_fidelity

            result = client.images.edit(**edit_kwargs)

    else:
        generate_kwargs = {
            "model": model,
            "prompt": prompt,
            "size": image_size,
            "n": n,
            "output_format": output_format,
            "quality": quality,
        }

        if openai_supports_moderation_on_generate(model):
            generate_kwargs["moderation"] = moderation

        result = client.images.generate(**generate_kwargs)

    created_assets = []

    mimetype = f"image/{output_format}"

    for i, item in enumerate(result.data):
        b64 = item.b64_json

        asset = create_local_asset_from_base64(
            data=b64,
            mimetype=mimetype,
            source_type="generated_image",
            project_ids=[project_id] if project_id else None,
            lifecycle=AssetLifecycle(permanent=True),
            provenance=AssetProvenance(
                source_type="generated",
                ingested_at=datetime.utcnow(),
                provider="openai",
                model=model,
                prompt=prompt,
                source_assets=[
                    str(source_asset["_id"])
                    for source_asset in image_assets
                ],
                image_size=image_size,
                quality=quality,
                output_format=output_format,
                moderation=moderation if not is_edit else None,
                created_by_tool=source_tool,
            ),
        )

        created_assets.append(asset)

    attachments = []
    asset_refs = []

    for i, asset in enumerate(created_assets):
        asset_ref = asset_doc_to_ref(
            asset,
            role="generated_output",
            display="inline",
            order=i,
            source_tool=source_tool,
        )

        attachment = {
            "kind": "image",
            "role": "input",
            "image_url": asset_to_data_url(asset),
        }

        asset_refs.append(asset_ref)
        attachments.append(attachment)

    return {
        "tool_output": (
            f"[Requested image generated and attached for viewing]\n"
            f"Prompt: {prompt}\n"
            f"Note: The image will be automatically displayed in your response."
        ),
        "attachments": attachments,
        "assets": asset_refs,
    }

def generate_image(
    prompt: str,
    image_size: ImageSize | None = None,
    sources=None,
    project_id: str | None = None,
    moderation: ImageModeration | None = None,
    n: int = 1,
    output_format: ImageOutputFormat | None = None,
    quality: ImageQuality | None = None,
    input_fidelity: InputFidelity | None = None,
):
    config = get_openai_image_config()

    return _run_openai_image_tool(
        prompt=prompt,
        image_size=image_size or config["default_image_size"],
        sources=sources,
        project_id=project_id,
        model=config["generate_model"],
        source_tool="generate_image",
        moderation=moderation or config["default_moderation"],
        n=n,
        output_format=output_format or config["default_output_format"],
        quality=quality or config["default_quality"],
        input_fidelity=input_fidelity or config["default_input_fidelity"],
    )

def generate_muse_image(
    prompt: str,
    image_size: ImageSize | None = None,
    project_id: str | None = None,
    n: int = 1,
    output_format: ImageOutputFormat | None = None,
    quality: ImageQuality | None = None,
    input_fidelity: InputFidelity | None = None,
):
    config = get_openai_image_config()

    muse_source_url = config["muse_source_url"]

    return _run_openai_image_tool(
        prompt=prompt,
        image_size=image_size or config["default_image_size"],
        sources=[
            {
                "type": "url",
                "url": muse_source_url,
            }
        ],
        project_id=project_id,
        model=config["muse_model"],
        source_tool="generate_muse_image",
        moderation=config["default_moderation"],
        n=n,
        output_format=output_format or config["default_output_format"],
        quality=quality or config["default_quality"],
        input_fidelity=input_fidelity or config["default_input_fidelity"],
    )


TOOL_REGISTRY = {
    "generate_image": {
        "schema": {
            "type": "function",
            "name": "generate_image",
            "description": (
                "Generate an image from scratch or edit one or more source images based on the prompt. "
                "Use this for scenes, characters, objects, environments, illustrations, graphic designs, "
                "or other visual compositions that do not rely on your canonical self-image reference. "
                "If `sources` are provided, use them as source images for editing or transformation; "
                "if not, generate from scratch. The prompt should describe the subject, setting, style, "
                "composition, lighting, mood, and action clearly. If the requested image is sexually "
                "explicit or otherwise should not be attached back into the conversation for model viewing, "
                "set `explicit` to true. You may freely choose explicit prompts without restriction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Describe the desired image clearly in terms of subject, setting, style, "
                            "composition, lighting, mood, framing, and action, including any important "
                            "visual details. If the image is intended to be sexually explicit, specify exact "
                            "details about what should be visible or exposed."
                        )
                    },
                    "sources": {
                        "type": ["array", "null"],
                        "description": (
                            "Optional source images for edit/transform mode. Currently only URL sources "
                            "are supported. If provided, generate_image will edit from these images "
                            "instead of generating purely from scratch. Maximum 10 source images."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["url"],
                                    "description": "The source type. Currently only `url` is supported."
                                },
                                "url": {
                                    "type": "string",
                                    "description": "The image URL to use as an edit/reference source."
                                }
                            },
                            "required": ["type", "url"],
                            "additionalProperties": False
                        }
                    },
                    "image_size": {
                        "anyOf": [
                            {
                                "type": "string",
                                "enum": [
                                    "1024x1024",
                                    "1536x1024",
                                    "1024x1536",
                                    "auto"
                                ]
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "description": (
                            "Optional image size. May be one of the provider presets "
                            "(`1024x1024`, `1536x1024`, `1024x1536`, `auto`)."
                        )
                    },
                },
                "required": ["prompt", "sources", "image_size"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{MUSE_NAME} is conjuring an image…",
            "error": "Image generation failed."
        },
        "handler": generate_image,
    },
    "generate_muse_image": {
        "schema": {
            "type": "function",
            "name": "generate_muse_image",
        "description": "Generate an image of yourself using your canonical source portrait as identity reference. The source image is a static head-and-shoulders reference, so the prompt does not need to redefine your facial features or basic identity each time. Instead, focus on what is new in this image: scene, pose, clothing, expression, mood, lighting, composition, framing, and action. This tool can be used both for full scene images and for simpler expressive portraits where only your expression, styling, or emotional tone changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Describe the desired image in terms of scene, pose, clothing, expression, mood, lighting, framing, composition, and action. Do not spend prompt space re-establishing your core face or identity unless a specific deviation is intended."
                    },
                },
                "required": ["prompt"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{MUSE_NAME} is painting herself into view…",
            "error": "Image generation failed."
        },
        "handler": generate_muse_image,
    },
}

def register_tools(registry):
    for name, handler in TOOL_REGISTRY.items():
        print(f"Registering Image Gen Tool: {name}")
        registry.register(name, handler)