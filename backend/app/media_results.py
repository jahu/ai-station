"""Final media executor identity from a saved reviewed output definition."""


def final_media_executor(media):
    if (
        media.get("kind") == "avatar"
        and (media.get("request") or {}).get("generation_profile") == "sonic_whole_768_v1"
    ):
        return "sonic_whole"
    return {
        "image": "photo_pipe",
        "music": "ace_step_music",
        "speech": "chatterbox",
        "video": "media_compose",
        "avatar": "media_compose",
    }.get(media.get("kind"))
