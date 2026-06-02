// /config/configMeta.js
export const SETTINGS_META = {
  user_config: {
    USER_NAME: {
      label: "Your name",
      description: "What your muse can call you in conversation.",
    },
    USER_TIMEZONE: {
      label: "Timezone",
      description: "Used for reminders and all time displays in the UI and in your muse's context.",
    },
    USER_COUNTRYCODE: {
      label: "Country",
      description: "Used to give your muse awareness of the weather where you are.",
    },
    USER_ZIPCODE: {
      label: "Zip/Postal Code",
      description: "Used to give your muse awareness of the weather and day/night cycle where you are.",
    },
    QUIET_HOURS: {
      label: "Quiet hours",
      description: "Hours during which your muse will not message you unprompted (if enabled)."
    },
    MEASUREMENT_UNITS: {
      label: "Measurement units",
      description: "Currently only used for your muse's weather awareness. Metric=Celsius, Imperial=Fahrenheit"
    }
  },
  llm_config: {
    OPENAI_API_KEY: {
      label: "OpenAI API Key",
      description: "Your personal OpenAI API key for use with MemoryMuse."
    },
    OPENAI_MODEL: {
      label: "Main Model",
      description: "Model for conversations.",
      options: [
        { value: "chatgpt-4o-latest", label: "chatgpt-4o-latest" },
        { value: "gpt-4.1", label: "gpt-4.1" },
        { value: "gpt-4.1-mini", label: "gpt-4.1-mini" },
        { value: "gpt-5-chat-latest", label: "gpt-5-chat-latest" },
        { value: "gpt-5", label: "gpt-5" },
        { value: "gpt-5-mini", label: "gpt-5-mini" },
        { value: "gpt-5.1-chat-latest", label: "gpt-5.1-chat-latest" },
        { value: "gpt-5.1", label: "gpt-5.1" },
        { value: "gpt-5.2-chat-latest", label: "gpt-5.2-chat-latest" },
        { value: "gpt-5.2", label: "gpt-5.2" },
        { value: "gpt-5.3-chat-latest", label: "gpt-5.3-chat-latest" },
        { value: "gpt-5.4", label: "gpt-5.4" },
        { value: "gpt-5.4-mini", label: "gpt-5.4-mini" },
        { value: "gpt-5.5", label: "gpt-5.5" },
      ],
    },
    OPENAI_FULL_MODEL: {
      label: "Heavy model",
      description: "Model used for journaling. Usually set to the same as the Main Model.",
      options: [
        { value: "chatgpt-4o-latest", label: "chatgpt-4o-latest" },
        { value: "gpt-4.1", label: "gpt-4.1" },
        { value: "gpt-4.1-mini", label: "gpt-4.1-mini" },
        { value: "gpt-5-chat-latest", label: "gpt-5-chat-latest" },
        { value: "gpt-5", label: "gpt-5" },
        { value: "gpt-5-mini", label: "gpt-5-mini" },
        { value: "gpt-5.1-chat-latest", label: "gpt-5.1-chat-latest" },
        { value: "gpt-5.1", label: "gpt-5.1" },
        { value: "gpt-5.2-chat-latest", label: "gpt-5.2-chat-latest" },
        { value: "gpt-5.2", label: "gpt-5.2" },
        { value: "gpt-5.3-chat-latest", label: "gpt-5.3-chat-latest" },
        { value: "gpt-5.4", label: "gpt-5.4" },
        { value: "gpt-5.4-mini", label: "gpt-5.4-mini" },
        { value: "gpt-5.5", label: "gpt-5.5" },
      ],
    },
    OPENAI_WHISPER_MODEL: {
      label: "Backend decisions model",
      description: "Model used for backend decision-making. Small and cheap.",
      options: [
        { value: "gpt-4.1-mini", label: "gpt-4.1-mini" },
        { value: "gpt-4.1-nano", label: "gpt-4.1-nano" },
        { value: "gpt-5-mini", label: "gpt-5-mini" },
        { value: "gpt-5-nano", label: "gpt-5-nano" },
        { value: "gpt-5.4-mini", label: "gpt-5.4-mini" },
        { value: "gpt-5.4-nano", label: "gpt-5.4-nano" },
      ],
    },
  },
  tts_config: {
    ELEVENLABS_API_KEY: {
      label: "ElevenLabs API Key",
      description:
        "The API Key for your ElvenLabs account.",
    },
    ELEVENLABS_MODEL: {
      label: "Model",
      description: "TTS Model.",
      options: [
        { value: "eleven_flash_v2_5", label: "eleven_flash_v2_5" },
        { value: "eleven_v3", label: "eleven_v3" },
      ],
    },
    ELEVENLABS_VOICE_ID: {
      label: "Voice ID",
      description:
        "The ID the TTS backend uses to choose which voice to use.",
    },
    ELEVENLABS_VOICE_SPEED: {
      label: "Voice Speed",
      description:
        "Speed adjustment for the chosen voice.",
    },
    ELEVENLABS_VOICE_SIMILARITY: {
      label: "Voice Similarity",
      description:
        "From ElevenLabs: High enhancement boosts overall voice clarity and target speaker similarity. Very high values can cause artifacts, so adjusting this setting to find the optimal value is encouraged.",
    },
    ELEVENLABS_VOICE_STABILITY: {
      label: "Voice Stability",
      description:
        "From ElevenLabs: Increasing stability will make the voice more consistent between re-generations, but it can also make it sounds a bit monotone. On longer text fragments we recommend lowering this value.",
    },
  },
  social_config: {
    DISCORD_TOKEN: {
      label: "Discord Token",
      description:
        "Your Discord token for programmatic access.",
    },
    DISCORD_GUILD_NAME: {
      label: "Discord Server Name",
      description:
        "The name of the Discord server your muse will connect to.",
    },
    DISCORD_CHANNEL_NAME: {
      label: "Discord Channel Name",
      description:
        "The channel in on the Discord server that your muse will listen to and speak within.",
    },
    PRIMARY_USER_DISCORD_ID: {
      label: "Your Discord user ID",
      description:
        "Your numerical Discord ID for your personal Discord account. Your muse will use this to recognize you there.",
    },
  },
  muse_features: {
    ENABLE_GCP: {
      label: "Global Consciousness Project Awareness",
      description:
        "If enabled, your muse will be aware of the Global Consciousness Project coherence status and may reference it in conversation.",
    },
    ENABLE_WEATHER: {
      label: "Weather Awareness",
      description:
        "If enabled, your muse will be aware of your local weather conditions and may reference them in conversation.",
    },
    ENABLE_SUN_MOON: {
      label: "Sun & Moon Awareness",
      description:
        "If enabled, your muse will be aware of your local day/night cycle and basic sun and moon information.",
    },
    ENABLE_SPACE_WEATHER: {
      label: "Space Weather Awareness",
      description:
        "If enabled, your muse will be aware of basic space weather (geomagnetic and solar activity) and may reference it in conversation.",
    },
    ENABLE_UNPROMPTED_MESSAGING: {
      label: "Unprompted messaging",
      description: "Allow your muse to occasionally message you first, outside of quiet hours.",
    },
    ENABLE_JOURNAL: {
      label: "Journal",
      description:
        "If enabled, your muse can keep a journal of their own reflections.",
    },
    ENABLE_PRIVATE_JOURNAL: {
      label: "Private Muse Journal",
      description:
        "If enabled, your muse can keep a private journal of their own reflections that are not shown in the main Journal tab.",
    },
    ENABLE_REMINDERS: {
      label: "Reminders",
      description:
        "If enabled, the Reminders tab and reminder system are available for scheduling nudges and alerts.",
    },
    ENABLE_THOUGHT_VIEW: {
      label: "Thought View",
      description:
        "Your muse has inner thoughts. If enabled, your muse’s inner thoughts will appear for you to see in their response.",
    },
    ENABLE_GM_VIEW: {
      label: "GM View",
      description:
        "When in Scene mode, your muse may leave notes for themselves in their response. If enabled, these will appear for you to see. We recommend keeping this disabled.",
    },
    ENABLE_MOTD: {
      label: "MOTD / Muse Message",
      description:
        "If enabled, your muse can set a short message of the day under their portrait in the UI.",
    },
    ENABLE_THREAD_EXTENDED_HISTORY: {
      label: "Thread Extended History",
      description:
        "If enabled, while in a thread, your muse will see the entire history of the thread. This can increase API costs.",
    },
    HIDE_SUMMARIZED_THREAD_MESSAGES: {
      label: "Skip summarized thread messages",
      description:
        "If enabled, in combination with Thread Extended History, messages already summarized in the thread will not appear in full to your muse. Disabling this will increase thread API costs.",
    },
    ENABLE_SCHEDULER: {
      label: "Scheduler.",
      description:
        "If enabled, properly registered tasks will run.",
    },
  },
};