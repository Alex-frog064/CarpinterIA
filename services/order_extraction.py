import re
import unicodedata
from typing import Any

from tools.carpentry_tools import obtener_menu
from tools.order_tools import merge_cart_items
from services.intent_service import is_clear_order_intent

GENERIC_CATEGORY_KEYWORDS = [
    "mueble",
    "puerta",
    "closet",
    "cocina",
    "mesa",
    "restauracion",
    "piso",
    "librero",
    "escalera",
    "ventana",
]

QUANTITY_PRODUCT_PATTERN = re.compile(
    r"(\d+)\s+([a-záéíóúñ\s]+?)(?=\s+y\s+|\s*,|\s*$|\s+\d+\s+)",
    re.IGNORECASE,
)

ORDER_KEYWORDS = re.compile(
    r"\b(quiero|quisiera|pedir|pido|ordenar|ordeno|comprar|cotizar|cotizo|me\s+das|dame|darme|necesito|necesitaria|me\s+gustaria|"
    r"puedes\s+darme|podr[ií]as\s+darme|regalame|ponme|hazme|arma|armame)\b",
    re.IGNORECASE,
)

CUSTOM_MEASURE_PATTERN = re.compile(
    r"(mis\s+medidas|a\s+medida|medidas?\s+propias?|medida\s+propia|"
    r"personalizado|personalizada|hecho\s+a\s+medida|seg[uú]n\s+mis|"
    r"con\s+mis\s+medidas|con\s+medidas)",
    re.IGNORECASE,
)

DIMENSION_LABELS = re.compile(
    r"(?:alto|altura)[:\s]+(\d+(?:[.,]\d+)?)\s*(?:cm|m)?\s*[,;\s]+"
    r"(?:ancho|anchura)[:\s]+(\d+(?:[.,]\d+)?)\s*(?:cm|m)?\s*[,;\s]+"
    r"(?:fondo|largo|profundidad|depth)[:\s]+(\d+(?:[.,]\d+)?)\s*(?:cm|m)?",
    re.IGNORECASE,
)

DIMENSION_NUMBERS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:cm|cent[ií]metros?)?\s*"
    r"[y,\s]+\s*(\d+(?:[.,]\d+)?)\s*(?:cm|cent[ií]metros?)?\s*"
    r"(?:[y,\s]+\s*(\d+(?:[.,]\d+)?)\s*(?:cm|cent[ií]metros?)?)?",
    re.IGNORECASE,
)


def extract_dimensions_from_text(text: str) -> dict | None:
    dims = {}
    labeled = DIMENSION_LABELS.search(text)
    if labeled:
        dims["ancho"] = float(labeled.group(1).replace(",", "."))
        dims["largo"] = float(labeled.group(2).replace(",", "."))
        dims["alto"] = float(labeled.group(3).replace(",", "."))
        return dims

    labeled2 = re.search(
        r"(?:ancho|anchura)[:\s]+(\d+(?:[.,]\d+)?)\s*(?:cm|m)?\s*[,;\s]+"
        r"(?:largo|fondo|profundidad)[:\s]+(\d+(?:[.,]\d+)?)\s*(?:cm|m)?",
        text, re.IGNORECASE,
    )
    if labeled2:
        dims["ancho"] = float(labeled2.group(1).replace(",", "."))
        dims["largo"] = float(labeled2.group(2).replace(",", "."))
        return dims

    nums = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:cm|m)?", text, re.IGNORECASE)
    clean_nums = []
    for n in nums:
        val = float(n.replace(",", "."))
        if 1 <= val <= 1000:
            clean_nums.append(val)

    if len(clean_nums) >= 3:
        dims["ancho"] = clean_nums[0]
        dims["largo"] = clean_nums[1]
        dims["alto"] = clean_nums[2]
    elif len(clean_nums) == 2:
        dims["ancho"] = clean_nums[0]
        dims["largo"] = clean_nums[1]

    return dims if dims else None


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _normalize_term(term: str) -> str:
    clean = _strip_accents(term.strip().lower())
    mapping = {
        "mueble": "mueble",
        "muebles": "mueble",
        "puerta": "puerta",
        "puertas": "puerta",
        "closet": "closet",
        "closets": "closet",
        "cocina": "cocina",
        "cocinas": "cocina",
        "mesa": "mesa",
        "mesas": "mesa",
        "librero": "librero",
        "libreros": "librero",
        "escalera": "escalera",
        "escaleras": "escalera",
        "ventana": "ventana",
        "ventanas": "ventana",
        "piso": "piso",
        "pisos": "piso",
        "restauracion": "restauracion",
    }
    if clean in mapping:
        return mapping[clean]
    if clean.endswith("es") and len(clean) > 4:
        return clean[:-2]
    if clean.endswith("s") and len(clean) > 3:
        return clean[:-1]
    return clean


def extract_generic_category(text: str) -> str | None:
    text_lower = _strip_accents(text.lower())
    for keyword in GENERIC_CATEGORY_KEYWORDS:
        normalized_keyword = _strip_accents(keyword.lower())
        if re.search(rf"\b{re.escape(normalized_keyword)}\b", text_lower):
            return _normalize_term(keyword)
    return None


def _is_generic_category_request(text: str, menu_names: list[str]) -> bool:
    category = extract_generic_category(text)
    if not category:
        return False

    text_lower = _strip_accents(text.lower())
    for name in menu_names:
        name_lower = _strip_accents(name.lower())
        if category in name_lower and name_lower in text_lower and name_lower != category:
            return False
        name_no_parens = re.sub(r"\s*\(.*?\)\s*", " ", name_lower).strip()
        if category in name_lower and name_no_parens in text_lower and name_no_parens != category:
            return False

    return True


async def extract_order_from_text(
    text: str, ollama_service: Any | None = None
) -> dict:
    """
    Identifica servicios y cantidades del texto del usuario.
    Usa LLM si está disponible; complementa con heurísticas regex.
    """
    menu = obtener_menu()["productos"]
    menu_names = [p["nombre"] for p in menu]
    extracted: list[dict] = []

    if ollama_service:
        try:
            llm_items = await ollama_service.extract_order_products(text, menu_names)
            extracted.extend(llm_items)
        except Exception:
            pass

    for fragment in _split_order_fragments(text):
        regex_items = _regex_extract(fragment, menu_names)
        for item in regex_items:
            _append_unique(extracted, item)
        single = _match_single_product(fragment, menu_names)
        if single:
            if single.get("_rejected"):
                return {
                    "productos_detectados": [],
                    "cart": [],
                    "added": [],
                    "errors": [single["mensaje"]],
                    "has_order_intent": True,
                }
            _append_unique(extracted, single)

    if not extracted and ORDER_KEYWORDS.search(text):
        single = _match_single_product(text, menu_names)
        if single:
            if single.get("_rejected"):
                return {
                    "productos_detectados": [],
                    "cart": [],
                    "added": [],
                    "errors": [single["mensaje"]],
                    "has_order_intent": True,
                }
            extracted.append(single)

    cart: list[dict] = []
    added, errors = merge_cart_items(cart, extracted)

    return {
        "productos_detectados": extracted,
        "cart": cart,
        "added": added,
        "errors": errors,
        "has_order_intent": bool(extracted) or is_clear_order_intent(text),
    }


def _split_order_fragments(text: str) -> list[str]:
    parts = re.split(r"\s+y\s+|\s*,\s*|\s+ también ", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def _append_unique(extracted: list[dict], item: dict):
    key = item.get("nombre") or item.get("categoria")
    if not key:
        extracted.append(item)
        return
    key = key.lower()
    for e in extracted:
        existing_key = (e.get("nombre") or e.get("categoria") or "").lower()
        if existing_key == key:
            e["cantidad"] = max(e["cantidad"], item["cantidad"])
            return
    extracted.append(item)


def _regex_extract(text: str, menu_names: list[str]) -> list[dict]:
    items = []
    text_lower = text.lower()

    for match in QUANTITY_PRODUCT_PATTERN.finditer(text_lower):
        qty = int(match.group(1))
        fragment = match.group(2).strip()

        product = _find_in_menu(fragment, menu_names)
        if product:
            items.append({"nombre": product, "cantidad": qty})
        else:
            category = extract_generic_category(fragment)
            if category:
                items.append({"categoria": category, "cantidad": qty})

    return items


SIZE_HINT_PATTERN = re.compile(
    r"\b(grande|peque[noa]?|mediano|mediana|media|extra\s+grande|chico|chica|enorme|"
    r"est[aá]ndar|normal|amplio|compacto)\b",
    re.IGNORECASE,
)

SIZE_HINT_MAP = {
    "media": "Mediano",
    "mediana": "Mediano",
    "mediano": "Mediano",
    "grande": "Grande",
    "pequeño": "Pequeño",
    "pequeña": "Pequeño",
    "pequeno": "Pequeño",
    "chico": "Pequeño",
    "chica": "Pequeño",
    "extra grande": "Extra Grande",
    "enorme": "Extra Grande",
    "estándar": "Mediano",
    "estandar": "Mediano",
    "normal": "Mediano",
    "amplio": "Grande",
    "compacto": "Pequeño",
}


FRACTIONAL_PRODUCT_PATTERN = re.compile(
    r"\b(media|medio|medias|medios|tercio|tercia|cuarto|cuarta|quinto|quinta)\s+"
    r"(silla|mesa|closet|cocina|librero|puerta|escalera|ventana|mueble)\b",
    re.IGNORECASE,
)


def _match_single_product(text: str, menu_names: list[str]) -> dict | None:
    text_lower = text.lower().strip()

    if FRACTIONAL_PRODUCT_PATTERN.search(text_lower):
        return {"_rejected": True, "mensaje": (
            "Lo siento, no es posible pedir medios o partes de un mueble. "
            "Cada producto se cotiza como unidad completa. "
            "¿Cuántas unidades necesitas?"
        )}

    text_lower = re.sub(
        r"^(quiero|quisiera|cotizar|cotizame|necesito|dame|me das|puedes darme|podr[ií]as darme|"
        r"un|una|unos|unas|dos|tres|cuatro|cinco|regalame|ponme|hazme|arma|armame|"
        r"la|las|los|el)\s+",
        "", text_lower,
    )

    custom_measure = bool(CUSTOM_MEASURE_PATTERN.search(text_lower))

    qty = 1
    size_hint = None
    if not custom_measure:
        size_match = SIZE_HINT_PATTERN.search(text_lower)
        if size_match:
            hint_text = size_match.group(1).strip().lower()
            size_hint = SIZE_HINT_MAP.get(hint_text)
            text_lower = text_lower[:size_match.start()] + text_lower[size_match.end():]
            text_lower = re.sub(r"\s+", " ", text_lower).strip()

    qty_match = re.search(r"\b(\d+|dos|tres|cuatro|cinco)\b", text_lower)
    if qty_match:
        qty_text = qty_match.group(1)
        if qty_text.isdigit():
            qty = int(qty_text)
        else:
            nums = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
            qty = nums.get(qty_text, 1)
        text_lower = text_lower.replace(qty_text, "", 1)

    if _is_generic_category_request(text_lower, menu_names):
        return None

    dims = extract_dimensions_from_text(text_lower)

    keywords = ["puerta", "closet", "cocina", "mesa", "piso", "librero", "escalera", "ventana"]
    for kw in keywords:
        if kw in text_lower:
            for name in menu_names:
                if kw in name.lower():
                    item = {"nombre": name, "cantidad": qty}
                    if size_hint:
                        item["tamano"] = size_hint
                    elif custom_measure or dims:
                        item["tamano"] = "A medida"
                    if dims:
                        item["dimensiones_extraidas"] = dims
                    return item

    best = None
    best_len = 0
    for name in menu_names:
        name_lower = name.lower()
        kws = [w for w in name_lower.split() if len(w) > 3]
        if name_lower in text_lower or any(k in text_lower for k in kws):
            if "restauracion" in name_lower or "restauración" in name_lower:
                continue
            if len(name) > best_len:
                best = name
                best_len = len(name)

    if best:
        item = {"nombre": best, "cantidad": qty}
        if size_hint:
            item["tamano"] = size_hint
        elif custom_measure or dims:
            item["tamano"] = "A medida"
        if dims:
            item["dimensiones_extraidas"] = dims
        return item
    return None


def _find_in_menu(fragment: str, menu_names: list[str]) -> str | None:
    fragment = fragment.strip().lower()
    if _is_generic_category_request(fragment, menu_names):
        return None

    fragment_norm = _strip_accents(fragment)
    for name in menu_names:
        name_norm = _strip_accents(name.lower())
        if fragment_norm in name_norm or name_norm in fragment_norm:
            return name
    keywords = fragment_norm.split()
    for name in menu_names:
        name_norm = _strip_accents(name.lower())
        if sum(1 for kw in keywords if kw in name_norm and len(kw) > 2) >= 1:
            return name
    return None
