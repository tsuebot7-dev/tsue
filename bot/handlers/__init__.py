from . import group_setup, start, browser, teacher_search, free_rooms, debug, save_and_group, my_group, language, rating, ai_intent, chat_log

routers = [
    group_setup.router,
    start.router,
    browser.router,
    teacher_search.router,
    free_rooms.router,
    debug.router,
    save_and_group.router,
    my_group.router,
    language.router,
    rating.router,
    ai_intent.router,
    chat_log.router,
]
