from .reach.tts.router import tts_router



def register(app):
    register_routers(app)
    register_prompt_profiles(app)
    register_commands(app)
    register_tools(app)
    register_scheduler_tasks()


def register_routers(app):
    app.include_router(tts_router)


def register_prompt_profiles(app):
    pass


def register_commands(app):
    pass


def register_tools(app):
    pass

def register_scheduler_tasks() -> None:
    from .reach.discoveryfeeds.scheduler_tasks import register_scheduler_tasks as register_discoveryfeeds

    register_discoveryfeeds()