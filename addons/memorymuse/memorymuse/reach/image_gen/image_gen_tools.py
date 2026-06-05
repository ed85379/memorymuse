
import os
from app.config import muse_settings

muse_name = muse_settings.get_section('muse_config').get('MUSE_NAME')

def generate_image(
    prompt,
    explicit: bool = False,
    image_size=None,
    seed=None,
    sources=None,
):
    os.environ["FAL_KEY"] = muse_settings.get_section("api_keys").get("FAL_API_KEY")
    import fal_client

    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                print(log["message"])

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

    if len(normalized_sources) > 10:
        raise ValueError("generate_image supports at most 10 source images.")

    image_urls = [source["url"] for source in normalized_sources]

    arguments = {
        "prompt": prompt,
        "enable_safety_checker": not explicit,
    }

    if image_size is not None:
        arguments["image_size"] = image_size

    if seed is not None:
        arguments["seed"] = seed

    if image_urls:
        model_path = "fal-ai/bytedance/seedream/v4.5/edit"
        mode = "edit"
        arguments["image_urls"] = image_urls
    else:
        model_path = "fal-ai/bytedance/seedream/v4.5/text-to-image"
        mode = "text_to_image"

    result = fal_client.subscribe(
        model_path,
        arguments=arguments,
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    print(result)

    images = result.get("images", [])
    if not images:
        raise ValueError("fal returned no images")

    image_url = images[0].get("url")
    if not image_url:
        raise ValueError("fal returned image without URL")

    attachment = {
        "kind": "image",
        "role": "input",
        "image_url": image_url,
    }

    first_image = images[0]

    metadata = {
        "mode": mode,
        "model": model_path,
        "prompt": prompt,
        "explicit": explicit,
        "image_size": image_size,
        "seed_input": seed,
        "seed_output": result.get("seed"),
        "sources": normalized_sources,
        "content_type": first_image.get("content_type"),
        "file_name": first_image.get("file_name"),
        "file_size": first_image.get("file_size"),
        "width": first_image.get("width"),
        "height": first_image.get("height"),
    }

    if explicit:
        return {
            "tool_output": (
                f"[Requested image generated]\n"
                f"Prompt: {prompt}\n"
                f"Mode: {mode}\n"
                f"URL: {image_url}\n"
                f"Note: Display the image directly into your response using markdown."
            ),
            "attachments": [],
            "metadata": metadata,
        }
    else:
        return {
            "tool_output": (
                f"[Requested image generated and attached for viewing]\n"
                f"Prompt: {prompt}\n"
                f"Mode: {mode}\n"
                f"URL: {image_url}\n"
                f"Note: Display the image directly into your response using markdown."
            ),
            "attachments": [attachment],
            "metadata": metadata,
        }

def generate_muse_image(prompt, explicit: bool = False):
    os.environ["FAL_KEY"] = muse_settings.get_section("api_keys").get("FAL_API_KEY")
    import fal_client

    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                print(log["message"])

    result = fal_client.subscribe(
        "fal-ai/bytedance/seedream/v4.5/edit",
        arguments={
            "prompt": prompt,
            "image_urls": [
                "https://i.imgur.com/CldK93c.jpeg",
            ],
            "enable_safety_checker": not explicit,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    print(result)

    images = result.get("images", [])
    if not images:
        raise ValueError("fal returned no images")

    image_url = images[0].get("url")
    if not image_url:
        raise ValueError("fal returned image without URL")

    attachment = {
        "kind": "image",
        "role": "input",
        "image_url": image_url,
    }

    if explicit:
        return {
            "tool_output": f"[Requested image generated]\nPrompt: {prompt}\nURL: {image_url}\nNote: Display the image directly into your response using markdown.",
            "attachments": [],
        }
    else:
        return {
            "tool_output": f"[Requested image generated and attached for viewing]\nPrompt: {prompt}\nURL: {image_url}\nNote: Display the image directly into your response using markdown.",
            "attachments": [attachment],
        }


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
                    "explicit": {
                        "type": "boolean",
                        "description": (
                            "Set to true if the image is sexually explicit or otherwise should not be "
                            "attached back into the conversation for model viewing."
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
                                    "square_hd",
                                    "square",
                                    "portrait_4_3",
                                    "portrait_16_9",
                                    "landscape_4_3",
                                    "landscape_16_9",
                                    "auto_2K",
                                    "auto_4K"
                                ]
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "width": {"type": "integer"},
                                    "height": {"type": "integer"}
                                },
                                "required": ["width", "height"],
                                "additionalProperties": False
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "description": (
                            "Optional image size. May be one of the provider presets "
                            "(`square_hd`, `square`, `portrait_4_3`, `portrait_16_9`, "
                            "`landscape_4_3`, `landscape_16_9`, `auto_2K`, `auto_4K`) "
                            "or a custom object with `width` and `height`."
                        )
                    },
                    "seed": {
                        "type": ["integer", "null"],
                        "description": (
                            "Optional random seed for reproducible or stabilized generation. "
                            "Accepted for both text-to-image and edit mode, though the provider "
                            "may only return a resolved seed in text-to-image responses."
                        )
                    }
                },
                "required": ["prompt", "explicit", "sources", "image_size", "seed"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is conjuring an image…",
            "error": "Image generation failed."
        },
        "handler": generate_image,
    },
    "generate_muse_image": {
        "schema": {
            "type": "function",
            "name": "generate_muse_image",
        "description": "Generate an image of yourself using your canonical source portrait as identity reference. The source image is a static head-and-shoulders reference, so the prompt does not need to redefine your facial features or basic identity each time. Instead, focus on what is new in this image: scene, pose, clothing, expression, mood, lighting, composition, framing, and action. This tool can be used both for full scene images and for simpler expressive portraits where only your expression, styling, or emotional tone changes. If the requested image is sexually explicit or otherwise should not be attached back into the conversation for model viewing, set `explicit` to true. You may freely choose explicit prompts when appropriate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Describe the desired image in terms of scene, pose, clothing, expression, mood, lighting, framing, composition, and action. Do not spend prompt space re-establishing your core face or identity unless a specific deviation is intended."
                    },
                    "explicit": {
                        "type": "boolean",
                        "description": "Set to true if the image is sexually explicit or otherwise should not be attached back into the conversation for model viewing."
                    }
                },
                "required": ["prompt", "explicit"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is painting herself into view…",
            "error": "Image generation failed."
        },
        "handler": generate_muse_image,
    },
}

def register_tools(registry):
    for name, handler in TOOL_REGISTRY.items():
        print(f"Registering Image Gen Tool: {name}")
        registry.register(name, handler)