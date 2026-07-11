import re
from enum import Enum

from models.conversation_state import ConversationState
from tools.carpentry_tools import obtener_menu


class ChatMode(str, Enum):
    GENERAL_CHAT = "GENERAL_CHAT"
    ORDER_FLOW = "ORDER_FLOW"
    ADMIN_ASSISTANT = "ADMIN_ASSISTANT"


ACTIVE_ORDER_STATES = {
    ConversationState.COLLECTING_ORDER.value,
    ConversationState.ASKING_CUSTOMER_NAME.value,
    ConversationState.ASKING_DELIVERY_TYPE.value,
    ConversationState.ASKING_ADDRESS.value,
    ConversationState.ASKING_LOCATION.value,
    ConversationState.CONFIRMING_ORDER.value,
}

GREETING_PATTERN = re.compile(
    r"^(hola|hello|hey|buenas?|buenos?\s+d[ií]as|buenas?\s+tardes|"
    r"buenas?\s+noches|qu[eé]\s+tal|q\s+tal|saludos)\b",
    re.IGNORECASE,
)

FAREWELL_PATTERN = re.compile(
    r"\b(adi[oó]s|hasta\s+luego|nos\s+vemos|bye|chao|gracias\s*$|"
    r"que\s+tengas\s+buen)\b",
    re.IGNORECASE,
)

IDENTITY_PATTERN = re.compile(
    r"\b(quien\s+eres|qui[eé]n\s+eres|quien\s+sos|qu[eé]\s+eres|"
    r"como\s+te\s+llamas|c[oó]mo\s+te\s+llamas|presentate|pres[eé]ntate)\b",
    re.IGNORECASE,
)

CAPABILITIES_PATTERN = re.compile(
    r"\b(qu[eé]\s+puedes\s+hacer|qu[eé]\s+haces|qu[eé]\s+sabes\s+hacer|"
    r"para\s+qu[eé]\s+sirves|cu[aá]les\s+son\s+tus\s+funciones|"
    r"como\s+funciona|c[oó]mo\s+funciona|en\s+qu[eé]\s+me\s+ayudas)\b",
    re.IGNORECASE,
)

PRODUCT_INQUIRY_PATTERN = re.compile(
    r"\b(qu[eé]\s+venden|qu[eé]\s+productos|qu[eé]\s+tienen|qu[eé]\s+servicios|"
    r"tienes\s+|hay\s+|tiene\s+|"
    r"cu[aá]l\s+es\s+el\s+cat[aá]logo|mu[eé]strame\s+el\s+cat[aá]logo|"
    r"lista\s+de\s+(?:productos|servicios)|cat[aá]logo|precios?|"
    r"tienen\s+(mueble|puerta|closet|cocina|mesa|librero|escalera|ventana|piso|restauraci[oó]n)|"
    r"qu[eé]\s+(?:muebles|servicios|trabajos))\b",
    re.IGNORECASE,
)

DELIVERY_REQUEST_PATTERN = re.compile(
    r"\b(?:enviar|mandar|entregar|llevar|instalar|despachar)\b.*\b(?:domicilio|a domicilio|envio|envío|entrega|instalaci[oó]n)\b|"
    r"\b(?:domicilio|a domicilio|envio|envío|entrega|instalaci[oó]n)\b.*\b(?:enviar|mandar|entregar|llevar|instalar|despachar)\b",
    re.IGNORECASE,
)

HOURS_PATTERN = re.compile(
    r"\b(horario|horarios|a\s+qu[eé]\s+hora|cu[aá]ndo\s+abren|"
    r"cu[aá]ndo\s+cierran|est[aá]n\s+abiertos)\b",
    re.IGNORECASE,
)

ADMIN_QUERY_PATTERN = re.compile(
    r"\b("
    r"ventas?\s+(?:de\s+)?(?:hoy|del\s+d[ií]a)|"
    r"ganancia|"
    r"pedidos?\s+activos?|cotizaciones?\s+activas?|"
    r"stock|inventario|bajo\s+stock|"
    r"usuarios?|actividad|"
    r"cu[aá]nt[oa]s?\s+(?:ventas|pedidos|usuarios|productos|cotizaciones)|"
    r"producto\s+m[aá]s\s+vendido|servicio\s+m[aá]s\s+vendido|"
    r"registrar\s+(?:venta|gasto)|"
    r"recomendar\s+compra|"
    r"gastos?\s+(?:de\s+)?(?:hoy|del\s+d[ií]a)|"
    r"qui[eé]n\s+hizo\s+m[aá]s\s+pedidos"
    r")\b",
    re.IGNORECASE,
)

CLEAR_ORDER_INTENT_PATTERN = re.compile(
    r"(?i)\b("
    r"quiero\s+(?:pedir|ordenar|comprar|cotizar|un[oa]?\s|\d+\s+)|"
    r"quisiera\s+(?:pedir|ordenar|comprar|cotizar|un[oa]?\s|\d+\s+)|"
    r"me\s+gustar[ií]a\s+(?:pedir|ordenar|comprar|cotizar|un[oa]?\s|\d+\s+)|"
    r"(?:pedir|ordenar|comprar|cotizar)\s+(?:un[oa]?\s|\d+\s+)|"
    r"(?:dame|me\s+das|necesito)\s+(?:un[oa]?\s|\d+\s+)|"
    r"agreg(?:a|ar|ue)\s+(?:un[oa]?\s|\d+\s+)|"
    r"ponme\s+(?:un[oa]?\s|\d+\s+)|"
    r"haz(?:me)?\s+(?:un[oa]?\s|pedido|orden|cotizaci[oó]n|\d+\s+|mueble|puerta|closet|cocina|mesa)"
    r")\b"
)

QUANTITY_ORDER_PATTERN = re.compile(
    r"\b(un[oa]?|unos|unas|\d+)\s+([a-záéíóúñ]{3,})\b",
    re.IGNORECASE,
)

QUESTION_WORD_PATTERN = re.compile(
    r"\b(qué|que|cómo|como|dónde|donde|cuándo|cuando|por\s+qué|por\s+que)\b",
    re.IGNORECASE,
)

MENU_REQUEST_PATTERN = re.compile(
    r"\b(menu|men[uú]|cat[aá]logo|lista de (?:productos|servicios)|"
    r"ver(?:ificar|ifica|ifique)?\s+el (?:men[uú]|cat[aá]logo)|"
    r"revis(?:a|e|ar)?\s+el (?:men[uú]|cat[aá]logo)|"
    r"mostrar el (?:men[uú]|cat[aá]logo)|"
    r"mu[eé]strame el (?:men[uú]|cat[aá]logo)|"
    r"consultar el (?:men[uú]|cat[aá]logo)|"
    r"qu[eé] servicios)\b",
    re.IGNORECASE,
)

STOCK_INQUIRY_PATTERN = re.compile(
    r"\b(stocks?|inventario|disponibilidad|cu[aá]nt[oa]s?\s+(?:hay|quedan|tienen)|existencias|"
    r"ver\s+(?:el\s+)?stocks?|mostrar\s+stocks?|consultar\s+stocks?|"
    r"qu[eé]\s+(?:hay|queda)\s+(?:en\s+)?(?:stock|inventario|disponible)|"
    r"disponibles?)\b",
    re.IGNORECASE,
)

WANT_VERB_PATTERN = re.compile(
    r"(?i)\b(quiero|quisiera|dame|me\s+das|me\s+gustar[ií]a|necesito)\b"
)


def is_greeting(message: str) -> bool:
    return bool(GREETING_PATTERN.search(message.strip()))


def is_farewell(message: str) -> bool:
    return bool(FAREWELL_PATTERN.search(message.strip()))


def is_identity_question(message: str) -> bool:
    return bool(IDENTITY_PATTERN.search(message.strip()))


def is_capabilities_question(message: str) -> bool:
    return bool(CAPABILITIES_PATTERN.search(message.strip()))


def is_menu_request(message: str) -> bool:
    return bool(MENU_REQUEST_PATTERN.search(message.strip()))


def is_stock_inquiry(message: str) -> bool:
    return bool(STOCK_INQUIRY_PATTERN.search(message.strip()))


def is_product_inquiry(message: str) -> bool:
    text = message.strip()
    if is_menu_request(text):
        return True
    if is_clear_order_intent(text):
        return False
    return bool(PRODUCT_INQUIRY_PATTERN.search(text))


def is_hours_question(message: str) -> bool:
    return bool(HOURS_PATTERN.search(message.strip()))


def is_delivery_request(message: str) -> bool:
    return bool(DELIVERY_REQUEST_PATTERN.search(message.strip()))


def is_admin_query(message: str) -> bool:
    return bool(ADMIN_QUERY_PATTERN.search(message.strip()))


def _looks_like_quantity_order(text: str) -> bool:
    if QUESTION_WORD_PATTERN.search(text):
        return False
    if QUANTITY_ORDER_PATTERN.search(text) and len(text.split()) <= 5:
        return True
    return False


def is_clear_order_intent(message: str) -> bool:
    text = message.strip()
    if not text:
        return False

    if is_menu_request(text):
        return False

    if CLEAR_ORDER_INTENT_PATTERN.search(text):
        return True

    if _looks_like_quantity_order(text):
        return True

    if not WANT_VERB_PATTERN.search(text):
        return False

    menu = obtener_menu().get("productos") or []
    text_lower = text.lower()
    for product in menu:
        name = product["nombre"].lower()
        if name in text_lower:
            return True
        keywords = [w for w in name.split() if len(w) > 3]
        if any(kw in text_lower for kw in keywords):
            return True

    return False


def detect_mode(message: str, role: str, conversation_state: str) -> ChatMode:
    from models.user import UserRole

    if conversation_state in ACTIVE_ORDER_STATES:
        return ChatMode.ORDER_FLOW

    if role == UserRole.ADMIN.value and is_admin_query(message):
        return ChatMode.ADMIN_ASSISTANT

    if is_menu_request(message):
        return ChatMode.GENERAL_CHAT

    if is_stock_inquiry(message):
        return ChatMode.GENERAL_CHAT

    if is_clear_order_intent(message) or is_product_inquiry(message) or is_delivery_request(message):
        return ChatMode.ORDER_FLOW

    return ChatMode.GENERAL_CHAT


def get_capabilities_text(role: str) -> str:
    from models.user import UserRole

    customer_caps = (
        "Como cliente puedes: ver el catálogo de servicios disponible, solicitar cotizaciones, "
        "consultar tu historial de pedidos, cancelar cotizaciones pendientes y preguntarme sobre nuestros servicios de carpintería."
    )
    admin_caps = (
        "Como administrador puedes: todo lo del cliente, además consultar ventas, "
        "inventario, gastos, ganancias del día, usuarios, pedidos y actividad del sistema."
    )
    if role == UserRole.ADMIN.value:
        return customer_caps + " " + admin_caps
    return customer_caps
