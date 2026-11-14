"""Reviewed conversation video settings reuse ordinary model and film admission."""


def selected_profile(session, parameters):
    from app.assistant import video_scope
    from app.video_models import profile_for

    scope = video_scope(parameters)
    return profile_for(
        session,
        scope.model_id if scope else None,
        requested_geometry=(scope.width, scope.height) if scope and scope.width is not None else None,
    )


def request_settings(scope, profile):
    """Freeze the selected native recipe; never apply the legacy 5B defaults to SVI."""
    values = scope.model_dump(mode="json", exclude={"memory_profile"}, exclude_none=True)
    recipe = profile.get("operation_recipe")
    if recipe:
        values.update({key: recipe[key] for key in ("width", "height", "steps", "cfg")})
    return values
