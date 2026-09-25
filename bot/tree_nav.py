"""
Talabalar/O'qituvchilar/Xonalar navigatsiyasi (browser.py) va Guruhga
avtomatik jadval sozlash (group_setup.py) bir xil daraxt bo'ylab
yurish mantig'idan foydalanadi - shu sabab umumiy qism shu yerga
chiqarildi."""

from . import data_loader

FEATURE_TREES = {
    "guruh": lambda: data_loader.store.guruhlar_tree,
    "ustoz": lambda: data_loader.store.ustozlar_tree,
    "xona": lambda: data_loader.store.xonalar_tree,
}

FEATURE_TITLES = {
    "guruh": "🎓 Talabalar",
    "ustoz": "👨‍🏫 O'qituvchilar",
    "xona": "🚪 Xonalar",
}


def get_node(tree: dict, path: list):
    node = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return {}
        node = node[key]
    return node


def effective_node(tree: dict, path: list) -> dict:
    """get_node natijasini qaytaradi, lekin agar u faqat bitta
    '__umumiy__' bolimidan iborat bolsa (yani manba faylida bu daraja
    uchun sarlavha umuman bolmagan bolsa - masalan kurslarga
    bolinmagan fakultet), foydalanuvchiga ortiqcha bosqich
    korsatmasdan, avtomatik ravishda ichkariga otib ketadi."""
    node = get_node(tree, path)
    while isinstance(node, dict) and list(node.keys()) == ["__umumiy__"]:
        inner = node["__umumiy__"]
        if not isinstance(inner, dict):
            break
        node = inner
    return node


def resolve_path_for_display(path: list) -> list:
    """path ichida foydalanuvchi ko'rmagan (avtomatik o'tkazilgan)
    '__umumiy__' segmentlarini yashirish uchun, breadcrumb va orqaga
    qaytish uchun 'toza' yo'lni hisoblaydi."""
    return [p for p in path if p != "__umumiy__"]


def path_title(feature: str, path: list) -> str:
    title = FEATURE_TITLES.get(feature, "")
    clean_path = resolve_path_for_display(path)
    if clean_path:
        pretty_path = [data_loader.display_name_for(p) for p in clean_path]
        title += " › " + " › ".join(pretty_path)
    return title


def pop_path(path: list) -> list:
    """'Orqaga' bosilganda path'dan bitta bosqichni (va unga ergashgan
    avtomatik '__umumiy__' hopini) olib tashlaydi."""
    if path:
        path = path[:-1]
    while path and path[-1] == "__umumiy__":
        path = path[:-1]
    return path


def next_path(path: list, raw_node: dict, node: dict, chosen_name: str) -> list:
    """Yangi elementga o'tilganda, agar shu darajada '__umumiy__' orqali
    avtomatik o'tib ketilgan bo'lsa, buni yangi path'ga ham aniq yozib
    qo'yadi - aks holda keyingi safar shu joyni qayta topa olmaymiz."""
    hop = ["__umumiy__"] if raw_node is not node and list(raw_node.keys()) == ["__umumiy__"] else []
    return path + hop + [chosen_name]
