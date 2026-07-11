# Reporte de Auditoría Final

**Fecha:** 2026-06-20  
**Resultado:** ✅ 7/7 pruebas automáticas pasadas

---

## Pruebas ejecutadas

| Caso | Descripción | Resultado |
|------|-------------|-----------|
| 1 | Flujo completo domicilio (frappe → confirmación) | ✅ PASS |
| 2 | Persistencia tras recarga (estado + carrito) | ✅ PASS |
| 3 | Frontend: SpeechRecognition y errores | ✅ PASS |
| 4 | Geolocalización guardada en DB | ✅ PASS |
| 5 | `registrar_venta()` descuenta inventario | ✅ PASS |
| 6 | Sin pedidos PENDING duplicados | ✅ PASS |
| 7 | `confirm_order()` idempotente (sin ventas duplicadas) | ✅ PASS |

Ejecutar pruebas:
```bash
python tests/audit_test.py
```

---

## Bugs corregidos

### 1. Ubicación GPS no reportaba herramienta ejecutada
**Problema:** `POST /location` avanzaba a `CONFIRMING_ORDER` pero no incluía `save_customer_location` en `tools_used`.  
**Corrección:** `order_agent.handle_location()` ahora retorna `['save_customer_location', 'calculate_order_total']`.

### 2. Conversaciones legacy sin fila en `conversation_state`
**Problema:** Conversaciones creadas antes de la tabla `conversation_state` fallaban al retomar el flujo.  
**Corrección:** `_ensure_state_row()` se invoca también para conversaciones existentes en `ChatService._ensure_conversation()`.

### 3. Riesgo de pedidos PENDING duplicados
**Problema:** Cada selección de tipo de entrega creaba un nuevo pedido en `orders`.  
**Corrección:** Nueva función `get_or_create_pending_order()` reutiliza el pedido PENDING activo.

### 4. Confirmación duplicada podía confundir al frontend
**Problema:** `confirm_order()` en pedido ya confirmado no dejaba log claro.  
**Corrección:** Log idempotente + retorno explícito `"Pedido ya confirmado"` sin re-registrar ventas.

### 5. Errores de geolocalización genéricos en frontend
**Problema:** Un solo mensaje para todos los errores GPS.  
**Corrección:** Mensajes específicos por código (`PERMISSION_DENIED`, `POSITION_UNAVAILABLE`, `TIMEOUT`).

### 6. Errores de micrófono genéricos en frontend
**Problema:** No se distinguía permiso denegado vs. sin voz vs. red.  
**Corrección:** Mapa de errores `not-allowed`, `no-speech`, `network`, `service-not-allowed`.

---

## Logs agregados (consola del servidor)

| Logger | Eventos |
|--------|---------|
| `carpentry.state` | Cambios de estado + conversation_id + items en carrito |
| `carpentry.tools` | Herramientas ejecutadas por mensaje |
| `carpentry.orders` | Pedidos creados, confirmados, reutilizados |
| `carpentry.sales` | Ventas registradas + stock restante |

Ejemplo de salida:
```
[INFO] carpentry.state | Estado → ASKING_CUSTOMER_NAME | conversation_id=857191d9 | cart_items=1
[INFO] carpentry.orders | Pedido creado #1 | conv=857191d9 | status=PENDING | total=$90.00
[INFO] carpentry.sales | Venta registrada | Frappe de oreo x1 | total=$65.00 | stock_restante=49.0
[INFO] carpentry.orders | Pedido confirmado #1 | ventas=1 | total=$90.00
```

---

## Verificaciones manuales recomendadas (demo)

1. **Micrófono:** Mantener presionado 🎤 en Chrome/Edge (requiere HTTPS o localhost).
2. **GPS:** Botón 📍 visible solo en estado `ASKING_LOCATION`.
3. **Recarga:** Copiar `conversation_id` del header, recargar, seleccionar conversación en sidebar.

---

## Archivos modificados en esta auditoría

- `services/audit_log.py` (nuevo)
- `services/conversation_state_service.py`
- `services/chat_service.py`
- `services/order_agent.py`
- `tools/order_tools.py`
- `tools/cafe_tools.py`
- `frontend/app.js`
- `tests/audit_test.py` (nuevo)
