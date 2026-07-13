const API = "";
const AUTH_KEY = "carpinteria_auth";
/** Logs temporales de depuración del chat (desactivar en producción) */
const CHAT_DEBUG = true;


const TOOL_LABELS = {
  consultar_inventario: "Consultar inventario",
  registrar_venta: "Registrar cotización",
  registrar_gasto: "Registrar gasto",
  obtener_producto_mas_vendido: "Servicio más cotizado",
  obtener_ganancia_dia: "Ganancia del día",
  productos_bajo_stock: "Materiales bajo stock",
  recomendar_compra: "Recomendar insumos",
  extract_order_from_text: "Detectar servicios",
  create_order: "Crear cotización",
  update_order: "Actualizar cotización",
  confirm_order: "Confirmar cotización",
  calculate_order_total: "Calcular total",
  save_customer_location: "Ubicación de instalación",
  get_active_order: "Cotización activa",
  cancel_order: "Cancelar cotización",
};

const STATE_LABELS = {
  IDLE: "Disponible",
  COLLECTING_ORDER: "Analizando cotización",
  ASKING_WOOD_TYPE: "Tipo de madera",
  ASKING_SIZE: "Tamaño del producto",
  ASKING_CUSTOMER_NAME: "Nombre del cliente",
  ASKING_DELIVERY_TYPE: "Tipo de entrega/instalación",
  ASKING_ADDRESS: "Dirección",
  ASKING_LOCATION: "Ubicación GPS",
  CONFIRMING_ORDER: "Confirmación",
  ORDER_COMPLETED: "Cotización registrada",
};

const ORDER_STATUS_LABELS = {
  PENDING: "Pendiente",
  CONFIRMED: "Confirmado",
  PREPARING: "En Producción",
  DELIVERING: "En Instalación",
  COMPLETED: "Completado",
  CANCELLED: "Cancelado",
};

const TIMELINE_STEPS = [
  "Cotización creada",
  "Confirmada",
  "En Producción",
  "En Instalación",
  "Completado",
];

const STATUS_PROGRESS = {
  PENDING: 0,
  CONFIRMED: 1,
  PREPARING: 2,
  DELIVERING: 3,
  COMPLETED: 4,
  CANCELLED: -1,
};

/** Estados donde se muestra el botón de ubicación GPS */
const LOCATION_STATES = ["ASKING_LOCATION"];

/** Estados activos del flujo de pedido */
const ORDER_FLOW_STATES = [
  "COLLECTING_ORDER",
  "ASKING_WOOD_TYPE",
  "ASKING_SIZE",
  "ASKING_CUSTOMER_NAME",
  "ASKING_DELIVERY_TYPE",
  "ASKING_ADDRESS",
  "ASKING_LOCATION",
  "CONFIRMING_ORDER",
];

/** Estado de confirmación antes de registrar el pedido */
const CONFIRMING_STATES = ["CONFIRMING_ORDER"];

/** Pedido finalizado en la conversación actual */
const ORDER_COMPLETED_STATES = ["ORDER_COMPLETED"];

const CUSTOMER_NAV = [
  { id: "chat", label: "Nueva cotización", icon: "💬" },
  { id: "orders", label: "Mis cotizaciones", icon: "📦" },
  { id: "conversations", label: "Mis conversaciones", icon: "📋" },
];

const ADMIN_NAV = [
  { id: "dashboard", label: "Dashboard", icon: "📊" },
  { id: "adminOrders", label: "Cotizaciones", icon: "📦" },
  { id: "users", label: "Usuarios", icon: "👥" },
  { id: "activity", label: "Actividad", icon: "📝" },
  { id: "products", label: "Servicios & Insumos", icon: "🪵" },
  { id: "woodTypes", label: "Tipos de Madera", icon: "🌳" },
  { id: "adminConversations", label: "Conversaciones", icon: "💬" },
  { id: "chat", label: "Chat admin", icon: "🤖" },
];

const state = {
  auth: null,
  currentView: "chat",
  conversationId: null,
  conversations: [],
  titles: {},
  isLoading: false,
  typing: false,
  typeSession: 0,
  cart: [],
  conversationState: "IDLE",
  speechSupported: false,
  recognition: null,
  isRecording: false,
};

const $ = (sel) => document.querySelector(sel);

function chatDebug(label, payload) {
  if (!CHAT_DEBUG) return;
  console.log(label, payload);
}

/** Normaliza texto del asistente desde distintos formatos de API */
function extractAssistantText(data) {
  if (data == null) return "";
  if (typeof data === "string") return data.trim();

  const candidates = [
    data.response,
    data.message,
    data.content,
    data.text,
    data.reply,
    data.answer,
    data?.message?.content,
    data?.choices?.[0]?.message?.content,
  ];

  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  return "";
}

function normalizeToolsUsed(toolsUsed) {
  if (!toolsUsed) return [];
  if (Array.isArray(toolsUsed)) {
    return toolsUsed.filter((t) => typeof t === "string" && t.trim());
  }
  if (typeof toolsUsed === "string") {
    try {
      const parsed = JSON.parse(toolsUsed);
      if (Array.isArray(parsed)) {
        return parsed.filter((t) => typeof t === "string" && t.trim());
      }
    } catch {
      return toolsUsed.trim() ? [toolsUsed.trim()] : [];
    }
  }
  return [];
}

function renderMessageContent(element, text) {
  const safe = String(text ?? "").trim();
  element.textContent = safe || "…";
  chatDebug("MESSAGE RENDER:", safe.slice(0, 120) || "(vacío)");
}

function loadAuth() {
  try {
    const raw = localStorage.getItem(AUTH_KEY) || sessionStorage.getItem(AUTH_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.auth?.token) {
    headers.Authorization = `Bearer ${state.auth.token}`;
  }
  return headers;
}

async function apiFetch(url, options = {}) {
  const res = await fetch(`${API}${url}`, {
    ...options,
    headers: authHeaders(options.headers || {}),
  });
  if (res.status === 401) {
    localStorage.removeItem(AUTH_KEY);
    sessionStorage.removeItem(AUTH_KEY);
    state.auth = null;
    if (isLandingPage()) {
      throw new Error("Sesión no válida. Inicia sesión para continuar.");
    }
    // Only redirect to /login from the /app page (not the landing page)
    window.location.href = "/login";
    throw new Error("Sesión expirada");
  }
  return res;
}

function isAdmin() {
  return state.auth?.user?.role === "ADMIN";
}

function isCustomer() {
  return state.auth?.user?.role === "CUSTOMER";
}

function formatOrderId(id) {
  return String(id).padStart(4, "0");
}

function formatTime(isoOrDate) {
  const d = isoOrDate ? new Date(isoOrDate) : new Date();
  return d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}

function formatFullDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("es", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getUserInitials() {
  const name = state.auth?.user?.full_name || state.auth?.user?.username || "U";
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function estimateDays(order) {
  const dt = (order.delivery_type || "").toLowerCase();
  return dt.includes("domicilio") || dt.includes("instalacion") ? 10 : 7;
}

function renderOrderTimeline(status) {
  if (status === "CANCELLED") {
    return `<div class="order-timeline cancelled"><p class="timeline-cancelled">Pedido cancelado</p></div>`;
  }
  const through = STATUS_PROGRESS[status] ?? 0;
  return `
    <div class="order-timeline">
      ${TIMELINE_STEPS.map((label, i) => {
        const done = i <= through;
        const icon = done ? "●" : "○";
        return `
          <div class="timeline-step ${done ? "done" : "pending"}">
            <span class="timeline-icon">${icon}</span>
            <span class="timeline-label">${label}</span>
          </div>`;
      }).join("")}
    </div>`;
}

function renderOrderConfirmationCard(card) {
  const itemsHtml = (card.items || [])
    .map((item) => {
      const props = [];
      if (item.madera) props.push(`🪵 ${escapeHtml(item.madera)}`);
      if (item.tamano) props.push(`📐 ${escapeHtml(item.tamano)}`);
      const propsStr = props.length ? `<span class="order-card-item-props">${props.join(" · ")}</span>` : "";
      const base = item.precio_base;
      const final_ = item.precio || item.subtotal / item.cantidad;
      const priceInfo = base && base !== final_
        ? `<span class="order-card-item-price-detail">Base: $${base.toFixed(2)} → $${final_.toFixed(2)}</span>`
        : `<span class="order-card-item-price">$${Number(item.subtotal || item.precio * item.cantidad).toFixed(2)}</span>`;
      return `<li>
        <span class="order-card-item-main">${item.cantidad}x ${escapeHtml(item.producto)}</span>
        ${propsStr}
        ${priceInfo}
      </li>`;
    })
    .join("");

  return `
    <div class="order-confirmed-card">
      <div class="order-card-header">
        <span class="order-card-check">✅</span>
        <div>
          <h3>Cotización confirmada</h3>
          <p class="order-card-id">Cotización #${formatOrderId(card.order_id)}</p>
        </div>
      </div>
      <div class="order-card-body">
        <div class="order-card-row">
          <span class="label">Cliente</span>
          <span class="value">${escapeHtml(card.customer_name || "—")}</span>
        </div>
        <div class="order-card-row">
          <span class="label">Productos</span>
          <ul class="order-card-items">${itemsHtml || "<li>Sin servicios</li>"}</ul>
        </div>
        ${card.subtotal && card.delivery_fee ? `
        <div class="order-card-row">
          <span class="label">Subtotal</span>
          <span class="value">$${Number(card.subtotal).toFixed(2)}</span>
        </div>
        <div class="order-card-row">
          <span class="label">Envío/Instalación</span>
          <span class="value">$${Number(card.delivery_fee).toFixed(2)}</span>
        </div>` : ""}
        <div class="order-card-row highlight">
          <span class="label">Total</span>
          <span class="value total">$${Number(card.total).toFixed(2)}</span>
        </div>
        <div class="order-card-row">
          <span class="label">Tiempo estimado</span>
          <span class="value">${card.estimated_days || estimateDays(card)} días hábiles</span>
        </div>
        <div class="order-card-row">
          <span class="label">Estado</span>
          <span class="status-badge status-${card.status}">${ORDER_STATUS_LABELS[card.status] || card.status}</span>
        </div>
      </div>
      ${renderOrderTimeline(card.status)}
    </div>`;
}

function appendOrderConfirmationCard(card) {
  const wrap = document.createElement("div");
  wrap.className = "message assistant order-card-message";
  wrap.innerHTML = `
    <div class="message-avatar avatar-carpinteria" title="ARCHI Carpenter">🪵</div>
    <div class="message-body">${renderOrderConfirmationCard(card)}</div>`;
  messagesEl.appendChild(wrap);
  scrollToBottom();
}

function renderCustomerOrderCard(order, showCancel = false) {
  const cancellable = showCancel && ["PENDING", "CONFIRMED"].includes(order.status);
  const eta = estimateDays(order);
  return `
    <article class="order-history-card">
      <div class="order-history-header">
        <div>
          <h3>Cotización #${formatOrderId(order.id)}</h3>
          <p class="order-history-date">${formatFullDate(order.created_at)}</p>
        </div>
        <span class="status-badge status-${order.status}">${ORDER_STATUS_LABELS[order.status] || order.status}</span>
      </div>
      <div class="order-history-meta">
        <div><span>Total</span><strong>$${Number(order.total).toFixed(2)}</strong></div>
        <div><span>Tiempo est.</span><strong>${eta} días</strong></div>
        <div><span>Entrega</span><strong>${escapeHtml(order.delivery_type || "—")}</strong></div>
      </div>
      ${renderOrderTimeline(order.status)}
      ${
        cancellable
          ? `<button class="btn-sm btn-danger order-cancel-btn" data-cancel="${order.id}">Cancelar pedido</button>`
          : ""
      }
    </article>`;
}

function showSplash() {
  $("#splashScreen")?.classList.remove("hidden");
  $("#appRoot")?.classList.add("app-hidden");
}

function hideSplash() {
  $("#splashScreen")?.classList.add("hidden");
  $("#appRoot")?.classList.remove("app-hidden");
}

const sidebar = $("#sidebar");
const sidebarOverlay = $("#sidebarOverlay");
const sidebarNav = $("#sidebarNav");
const conversationList = $("#conversationList");
const messagesEl = $("#messages");
const welcomeCard = $("#welcomeCard");
const chatForm = $("#chatForm");
const messageInput = $("#messageInput");
const btnSend = $("#btnSend");
const btnMic = $("#btnMic");
const btnLocation = $("#btnLocation");
const conversationIdDisplay = $("#conversationIdDisplay");
const conversationStateDisplay = $("#conversationStateDisplay");
const chatArea = $("#chatArea");
const statusBanner = $("#statusBanner");
const cartItems = $("#cartItems");
const cartTotal = $("#cartTotal");
const cartTotalAmount = $("#cartTotalAmount");
const recordingOverlay = $("#recordingOverlay");
const inputHint = $("#inputHint");
const viewTitle = $("#viewTitle");

const isLandingPage = () => !!document.getElementById("appLanding");

document.addEventListener("DOMContentLoaded", () => {
  if (isLandingPage()) {
    bootstrapLanding();
  } else {
    bootstrap();
  }
});

async function bootstrapLanding() {
  showSplash();
  try {
    sessionStorage.removeItem(AUTH_KEY);
    state.auth = loadAuth();
    if (state.auth?.token) {
      try {
        // Guard against a hung request (e.g. backend unreachable) so the
        // splash screen never blocks the page indefinitely.
        const timeout = new Promise((_, reject) =>
          setTimeout(() => reject(new Error("timeout")), 5000)
        );
        const res = await Promise.race([apiFetch("/auth/me"), timeout]);
        if (res.ok) {
          state.auth.user = await res.json();
          localStorage.setItem(AUTH_KEY, JSON.stringify(state.auth));
        } else {
          localStorage.removeItem(AUTH_KEY);
          sessionStorage.removeItem(AUTH_KEY);
          state.auth = null;
        }
      } catch {
        localStorage.removeItem(AUTH_KEY);
        sessionStorage.removeItem(AUTH_KEY);
        state.auth = null;
      }
    } else {
      localStorage.removeItem(AUTH_KEY);
      state.auth = null;
    }
    await sleep(700);
  } finally {
    // Always hide the splash, even if something above throws unexpectedly,
    // so the home page is never left unscrollable behind it.
    $("#splashScreen")?.classList.add("hidden");
    initLandingChat();
  }
}

function initLandingChat() {
  if (!chatForm || !messageInput) return;

  chatForm.addEventListener("submit", handleSubmit);
  messageInput.addEventListener("keydown", handleKeydown);
  messageInput.addEventListener("input", autoResizeTextarea);
  btnLocation?.addEventListener("click", shareLocation);

  document.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      messageInput.value = chip.dataset.prompt;
      autoResizeTextarea();
      messageInput.focus();
      handleSubmit(new Event("submit"));
    });
  });

  initSpeechRecognition();
  inputHint.textContent = "Cotiza muebles, clósets, cocinas y más · Mantén el micrófono para hablar";
}

async function bootstrap() {
  showSplash();
  state.auth = loadAuth();
  // Allow opening the app without being authenticated. Authentication will
  // be required when the user tries to use the chat to create a quotation.
  // If a token exists, we'll verify it; otherwise continue as guest.
  if (!state.auth?.token) {
    state.auth = null;
  }

  try {
    const res = await apiFetch("/auth/me");
    if (res.ok) {
      state.auth.user = await res.json();
      localStorage.setItem(AUTH_KEY, JSON.stringify(state.auth));
    }
  } catch {
    localStorage.removeItem(AUTH_KEY);
    window.location.href = "/";
    return;
  }

  await sleep(400);
  hideSplash();
  init();
}

function init() {
  // Populate user badge — support guest mode when state.auth is null
  if (state.auth && state.auth.user) {
    $("#userName").textContent = state.auth.user.full_name || state.auth.user.username;
    $("#userRole").textContent = isAdmin() ? "Administrador" : "Cliente";
  } else {
    $("#userName").textContent = "Invitado";
    $("#userRole").textContent = "Visitante";
  }

  const btnLogoutEl = $("#btnLogout");
  if (btnLogoutEl) btnLogoutEl.addEventListener("click", handleLogout);
  $("#btnMenu").addEventListener("click", toggleSidebar);
  sidebarOverlay.addEventListener("click", closeSidebar);
  chatForm.addEventListener("submit", handleSubmit);
  messageInput.addEventListener("keydown", handleKeydown);
  messageInput.addEventListener("input", autoResizeTextarea);
  if (btnLocation) btnLocation.addEventListener("click", shareLocation);

  document.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      messageInput.value = chip.dataset.prompt;
      autoResizeTextarea();
      messageInput.focus();
      handleSubmit(new Event("submit"));
    });
  });

  if (isAdmin()) {
    document.querySelectorAll(".admin-only").forEach((el) => el.classList.remove("hidden"));
    document.querySelectorAll(".customer-only").forEach((el) => el.classList.add("hidden"));
    inputHint.textContent = "Chat administrativo: inventario, ventas, gastos, pedidos";
  } else {
    inputHint.textContent = "Mantén presionado el micrófono para hablar · Di 'cancelar mi pedido' para anular";
  }

  renderSidebarNav();
  initSpeechRecognition();
  switchView(isAdmin() ? "dashboard" : "chat");
}

function renderSidebarNav() {
  if (!sidebarNav) return;
  const items = isAdmin() ? ADMIN_NAV : CUSTOMER_NAV;
  sidebarNav.innerHTML = items
    .map(
      (item) => `
      <button class="nav-item${state.currentView === item.id ? " active" : ""}" data-view="${item.id}" type="button">
        <span class="nav-icon">${item.icon}</span>
        <span>${item.label}</span>
      </button>`
    )
    .join("");

  sidebarNav.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const viewId = btn.dataset.view;
      if (!isAdmin() && viewId === "chat") {
        startNewConversation();
      } else {
        switchView(viewId);
      }
      closeSidebar();
    });
  });
}

function switchView(viewId) {
  if (!document.getElementById("appRoot")) return;
  state.currentView = viewId;

  document.querySelectorAll(".view-panel").forEach((p) => p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));

  const titles = {
    chat: isAdmin() ? "Chat administrativo" : "Asistente de Cotizaciones",
    orders: "Mis cotizaciones",
    conversations: "Mis conversaciones",
    dashboard: "Dashboard del Taller",
    adminOrders: "Cotizaciones",
    users: "Usuarios",
    activity: "Actividad",
    products: "Servicios & Materiales",
    woodTypes: "Tipos de Madera",
    adminConversations: "Conversaciones",
  };
  viewTitle.textContent = titles[viewId] || "ARCHI Carpenter";

  if (viewId === "chat") {
    $("#viewChat").classList.add("active");
    $("#chatInputArea").classList.remove("hidden");
  } else if (viewId === "orders") {
    $("#viewOrders").classList.add("active");
    loadMyOrders();
  } else if (viewId === "conversations") {
    $("#viewChat").classList.add("active");
    loadConversations();
  } else if (viewId === "dashboard") {
    $("#viewDashboard").classList.add("active");
    loadDashboard();
  } else if (viewId === "adminOrders") {
    $("#viewAdminOrders").classList.add("active");
    loadAdminOrders();
  } else if (viewId === "users") {
    $("#viewUsers").classList.add("active");
    loadUsers();
  } else if (viewId === "activity") {
    $("#viewActivity").classList.add("active");
    loadActivity();
  } else if (viewId === "products") {
    $("#viewProducts").classList.add("active");
    loadProducts();
  } else if (viewId === "woodTypes") {
    $("#viewWoodTypes").classList.add("active");
    loadWoodTypes();
  } else if (viewId === "adminConversations") {
    $("#viewAdminConversations").classList.add("active");
    loadAdminConversations();
  }

  const activeNav = sidebarNav.querySelector(`[data-view="${viewId}"]`);
  if (activeNav) activeNav.classList.add("active");

  renderSidebarNav();
  if (viewId === "chat" || viewId === "conversations") {
    loadConversations();
  }
}

async function handleLogout() {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } catch {
    /* ignore */
  }
  localStorage.removeItem(AUTH_KEY);
  window.location.href = "/";
}

async function loadMyOrders() {
  const el = $("#myOrdersTable");
  el.innerHTML = '<div class="loading-inline">Cargando pedidos...</div>';
  try {
    const res = await apiFetch("/my/orders");
    if (!res.ok) throw new Error("Error al cargar pedidos");
    const orders = await res.json();
    if (!orders.length) {
      el.innerHTML = '<p class="empty-msg">No tienes pedidos aún.</p>';
      return;
    }
    el.innerHTML = orders.map((o) => renderCustomerOrderCard(o, true)).join("");
    el.querySelectorAll("[data-cancel]").forEach((btn) => {
      btn.addEventListener("click", () => cancelOrder(parseInt(btn.dataset.cancel, 10)));
    });
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function cancelOrder(orderId) {
  if (!confirm(`¿Cancelar pedido #${orderId}?`)) return;
  try {
    const res = await apiFetch(`/my/orders/${orderId}/cancel`, { method: "POST" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "No se pudo cancelar");
    }
    showStatusBanner(`Pedido #${orderId} cancelado`, "success");
    loadMyOrders();
  } catch (err) {
    showStatusBanner(err.message, "warning");
  }
}

function renderOrdersTable(orders, showCancel = false) {
  return `
    <table class="data-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Estado</th>
          <th>Total</th>
          <th>Entrega</th>
          <th>Fecha</th>
          ${showCancel ? "<th></th>" : "<th>Usuario</th>"}
        </tr>
      </thead>
      <tbody>
        ${orders
          .map((o) => {
            const cancellable = showCancel && ["PENDING", "CONFIRMED"].includes(o.status);
            return `
          <tr>
            <td>${o.id}</td>
            <td><span class="status-badge status-${o.status}">${ORDER_STATUS_LABELS[o.status] || o.status}</span></td>
            <td>$${Number(o.total).toFixed(2)}</td>
            <td>${escapeHtml(o.delivery_type || "—")}</td>
            <td>${formatDate(o.created_at)}</td>
            ${
              showCancel
                ? cancellable
                  ? `<td><button class="btn-sm btn-danger" data-cancel="${o.id}">Cancelar</button></td>`
                  : "<td></td>"
                : `<td>${escapeHtml(o.full_name || o.username || "—")}</td>`
            }
          </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;
}

async function loadDashboard() {
  const el = $("#statsGrid");
  el.innerHTML = '<div class="loading-inline">Cargando métricas...</div>';
  try {
    const res = await apiFetch("/admin/dashboard");
    if (!res.ok) throw new Error("Error al cargar dashboard");
    const stats = await res.json();
    el.innerHTML = `
      <div class="dashboard-card dashboard-sales">
        <span class="dashboard-icon">💰</span>
        <span class="dashboard-value">$${Number(stats.ventas_dia).toFixed(2)}</span>
        <span class="dashboard-label">Ventas del día</span>
      </div>
      <div class="dashboard-card dashboard-active">
        <span class="dashboard-icon">📦</span>
        <span class="dashboard-value">${stats.pedidos_activos}</span>
        <span class="dashboard-label">Pedidos activos</span>
      </div>
      <div class="dashboard-card dashboard-cancelled">
        <span class="dashboard-icon">🚫</span>
        <span class="dashboard-value">${stats.pedidos_cancelados}</span>
        <span class="dashboard-label">Pedidos cancelados</span>
      </div>
      <div class="dashboard-card dashboard-users">
        <span class="dashboard-icon">👥</span>
        <span class="dashboard-value">${stats.usuarios_registrados}</span>
        <span class="dashboard-label">Usuarios registrados</span>
      </div>`;
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function loadAdminOrders() {
  const el = $("#adminOrdersTable");
  el.innerHTML = "Cargando...";
  try {
    const res = await apiFetch("/admin/orders");
    const orders = await res.json();
    el.innerHTML = orders.length ? renderOrdersTable(orders, false) : '<p class="empty-msg">Sin pedidos.</p>';
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function loadUsers() {
  const el = $("#usersTable");
  try {
    const res = await apiFetch("/admin/users");
    const users = await res.json();
    el.innerHTML = `
      <table class="data-table">
        <thead><tr><th>ID</th><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Registro</th></tr></thead>
        <tbody>${users
          .map(
            (u) => `
          <tr>
            <td>${u.id}</td>
            <td>${escapeHtml(u.username)}</td>
            <td>${escapeHtml(u.full_name)}</td>
            <td>${u.role}</td>
            <td>${formatDate(u.created_at)}</td>
          </tr>`
          )
          .join("")}</tbody>
      </table>`;
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function loadActivity() {
  const el = $("#activityTable");
  try {
    const res = await apiFetch("/admin/activity");
    const rows = await res.json();
    el.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Detalle</th></tr></thead>
        <tbody>${rows
          .map(
            (a) => `
          <tr>
            <td>${formatDate(a.created_at)}</td>
            <td>${escapeHtml(a.full_name || a.username)}</td>
            <td><span class="action-badge">${a.action}</span></td>
            <td class="details-cell">${escapeHtml(JSON.stringify(a.details || {}))}</td>
          </tr>`
          )
          .join("")}</tbody>
      </table>`;
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

// loadProducts moved to bottom of file (enhanced version with catalog + sizes)

async function saveProductRow(row) {
  const id = parseInt(row.dataset.productId, 10);
  const stock = parseFloat(row.querySelector(".product-stock").value);
  const price = parseFloat(row.querySelector(".product-price").value);
  const menu_visible = row.querySelector(".product-active").checked;
  const btn = row.querySelector(".product-save");

  btn.disabled = true;
  btn.textContent = "…";

  try {
    const res = await apiFetch(`/admin/products/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stock, price, menu_visible }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Error al guardar");
    }
    btn.textContent = "✓";
    btn.classList.add("saved");
    showStatusBanner("Producto actualizado", "success");
    setTimeout(() => {
      btn.textContent = "Guardar";
      btn.classList.remove("saved");
      btn.disabled = false;
    }, 1500);
  } catch (err) {
    btn.textContent = "Guardar";
    btn.disabled = false;
    showStatusBanner(err.message, "warning");
  }
}

async function loadAdminConversations() {
  const el = $("#adminConversationsTable");
  try {
    const res = await apiFetch("/admin/conversations");
    const convs = await res.json();
    el.innerHTML = `
      <table class="data-table">
        <thead><tr><th>ID</th><th>Usuario</th><th>Estado</th><th>Mensajes</th><th>Fecha</th></tr></thead>
        <tbody>${convs
          .map(
            (c) => `
          <tr>
            <td>${c.id.slice(0, 8)}…</td>
            <td>${escapeHtml(c.full_name || c.username || "—")}</td>
            <td>${STATE_LABELS[c.state] || c.state}</td>
            <td>${c.message_count}</td>
            <td>${formatDate(c.created_at)}</td>
          </tr>`
          )
          .join("")}</tbody>
      </table>`;
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    if (isCustomer()) {
      inputHint.textContent = "Tu navegador no soporta voz. Puedes escribir tu pedido.";
    }
    btnMic.disabled = true;
    return;
  }

  state.speechSupported = true;
  state.recognition = new SpeechRecognition();
  state.recognition.lang = "es-MX";
  state.recognition.interimResults = false;
  state.recognition.maxAlternatives = 1;

  state.recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript.trim();
    if (transcript) {
      messageInput.value = transcript;
      autoResizeTextarea();
      handleSubmit(new Event("submit"));
    }
  };

  state.recognition.onerror = (event) => {
    stopRecording();
    const errorMessages = {
      "not-allowed": "Permiso de micrófono denegado.",
      "no-speech": "No se detectó voz.",
    };
    const msg = errorMessages[event.error];
    if (msg) showStatusBanner(msg, "warning");
  };

  state.recognition.onend = () => stopRecording();

  btnMic.addEventListener("click", (e) => {
    e.preventDefault();
    if (!state.speechSupported || state.isLoading) return;
    if (state.isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });
  btnMic.addEventListener("touchstart", (e) => {
    e.preventDefault();
    if (!state.isRecording) startRecording();
  });
  btnMic.addEventListener("touchend", (e) => {
    e.preventDefault();
    if (state.isRecording) stopRecording();
  });
}

function startRecording() {
  if (!state.speechSupported || state.isLoading || state.isRecording) return;
  state.isRecording = true;
  btnMic.classList.add("recording");
  recordingOverlay.classList.remove("hidden");
  showStatusBanner("Escuchando...", "listening");
  try {
    state.recognition.start();
  } catch {
    stopRecording();
  }
}

function stopRecording() {
  if (!state.isRecording) return;
  state.isRecording = false;
  btnMic.classList.remove("recording");
  recordingOverlay.classList.add("hidden");
  hideStatusBanner();
  try {
    state.recognition.stop();
  } catch {
    /* ignore */
  }
}

async function shareLocation() {
  if (!state.conversationId) {
    showStatusBanner("Envía un mensaje primero para iniciar la conversación.", "warning");
    return;
  }
  if (!navigator.geolocation) {
    showStatusBanner("Tu navegador no soporta geolocalización.", "warning");
    return;
  }

  btnLocation.disabled = true;
  showStatusBanner("Obteniendo ubicación...", "info");

  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      try {
        const res = await apiFetch("/location", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conversation_id: state.conversationId,
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
          }),
        });
        if (!res.ok) throw new Error("Error al enviar ubicación");
        const data = await res.json();
        chatDebug("CHAT RESPONSE (location):", data);
        await applyChatResponse(data);
        showStatusBanner("Ubicación recibida ✓", "success");
        setTimeout(hideStatusBanner, 3000);
      } catch (err) {
        showStatusBanner(err.message || "Error al enviar ubicación", "warning");
      } finally {
        btnLocation.disabled = false;
      }
    },
    () => {
      showStatusBanner("No se pudo obtener la ubicación.", "warning");
      btnLocation.disabled = false;
    },
    { enableHighAccuracy: true, timeout: 15000 }
  );
}

function toggleSidebar() {
  sidebar.classList.toggle("open");
  sidebarOverlay.classList.toggle("visible");
}

function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarOverlay.classList.remove("visible");
}

function autoResizeTextarea() {
  messageInput.style.height = "auto";
  messageInput.style.height = Math.min(messageInput.scrollHeight, 160) + "px";
}

function handleKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSubmit(e);
  }
}

async function loadConversations() {
  if (!conversationList) return;
  try {
    const res = await apiFetch("/conversations");
    if (!res.ok) throw new Error("Error al cargar conversaciones");
    state.conversations = await res.json();
    renderConversationList();
  } catch {
    if (conversationList) conversationList.innerHTML = '<li class="conversation-empty">No se pudieron cargar</li>';
  }
}

function renderConversationList() {
  if (!conversationList) return;
  if (!state.conversations.length) {
    conversationList.innerHTML = '<li class="conversation-empty">Sin conversaciones aún</li>';
    return;
  }

  conversationList.innerHTML = state.conversations
    .map((conv) => {
      const isActive = conv.id === state.conversationId;
      const title = state.titles[conv.id] || `Chat ${conv.id.slice(0, 8)}…`;
      const date = formatDate(conv.created_at);
      const stateLabel = STATE_LABELS[conv.state] || "";
      const userLabel = isAdmin() && conv.full_name ? ` · ${conv.full_name}` : "";
      return `
        <li class="conversation-item${isActive ? " active" : ""}" data-id="${conv.id}">
          <div class="conversation-row">
            <div>
              <span class="conversation-title">${escapeHtml(title)}</span>
              <span class="conversation-meta">${conv.message_count} msgs · ${date}${stateLabel ? ` · ${stateLabel}` : ""}${userLabel}</span>
            </div>
            <button class="conversation-delete-btn" type="button" data-delete="${conv.id}" title="Eliminar chat">✕</button>
          </div>
        </li>`;
    })
    .join("");

  conversationList.querySelectorAll(".conversation-item").forEach((item) => {
    item.addEventListener("click", () => {
      switchView("chat");
      selectConversation(item.dataset.id);
    });
  });

  conversationList.querySelectorAll(".conversation-delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const id = btn.dataset.delete;
      if (!id) return;
      const confirmed = confirm("¿Eliminar esta conversación? Esta acción no se puede deshacer.");
      if (!confirmed) return;
      await deleteConversation(id);
    });
  });
}

async function selectConversation(id) {
  if (state.isLoading) return;

  state.conversationId = id;
  updateConversationIdDisplay();
  const conv = state.conversations.find((c) => c.id === id);
  updateConversationStateDisplay(conv?.state || "IDLE");
  renderConversationList();
  closeSidebar();

  welcomeCard.classList.add("hidden");
  messagesEl.innerHTML = "";

  try {
    const [msgRes, stateRes] = await Promise.all([
      apiFetch(`/conversations/${id}/messages`),
      apiFetch(`/conversations/${id}/state`),
    ]);
    if (!msgRes.ok) throw new Error("Conversación no encontrada");
    const messages = await msgRes.json();

    if (stateRes.ok) {
      const st = await stateRes.json();
      updateCart(st.cart || []);
      updateConversationStateDisplay(st.state);
      updateLocationButton(st.state);
    }

    const firstUser = messages.find((m) => m.role === "user");
    if (firstUser) {
      state.titles[id] = truncate(firstUser.content, 40);
      renderConversationList();
    }

    messages.forEach((msg) => {
      if (msg.role === "user" || msg.role === "assistant") {
        const text = msg.role === "assistant" ? extractAssistantText(msg) : msg.content;
        appendMessage(msg.role, text, msg.tools_used, false, msg.created_at);
      }
    });

    scrollToBottom();
  } catch {
    appendMessage("assistant", "No se pudo cargar el historial.", null, false);
  }
}

function startNewConversation() {
  if (state.isLoading) return;
  switchView("chat");

  state.conversationId = null;
  state.cart = [];
  updateConversationIdDisplay();
  updateConversationStateDisplay("IDLE");
  updateCart([]);
  updateLocationButton("IDLE");
  messagesEl.innerHTML = "";
  welcomeCard.classList.remove("hidden");
  messageInput.value = "";
  autoResizeTextarea();
  renderConversationList();
  closeSidebar();
  messageInput.focus();
}

function updateConversationIdDisplay() {
  if (!conversationIdDisplay) return;
  conversationIdDisplay.textContent = state.conversationId
    ? `ID: ${state.conversationId}`
    : "Nueva conversación";
}

function updateConversationStateDisplay(convState) {
  state.conversationState = convState || "IDLE";
  if (!conversationStateDisplay) {
    updateLocationButton(convState);
    return;
  }
  if (!convState || convState === "IDLE") {
    conversationStateDisplay.classList.add("hidden");
    conversationStateDisplay.textContent = "";
    return;
  }
  conversationStateDisplay.classList.remove("hidden");
  conversationStateDisplay.textContent = STATE_LABELS[convState] || convState;
  updateLocationButton(convState);
}

function updateLocationButton(convState) {
  if (LOCATION_STATES.includes(convState)) {
    btnLocation.classList.remove("hidden");
  } else {
    btnLocation.classList.add("hidden");
  }
}

function updateCart(cart) {
  state.cart = cart || [];
  let total = 0;

  if (!state.cart.length) {
    if (cartItems) cartItems.innerHTML = '<p class="cart-empty">Sin servicios aún</p>';
    cartTotal?.classList.add("hidden");
    $("#chatbotCartSummary")?.classList.add("hidden");
    return;
  }

  if (cartItems) cartItems.innerHTML = state.cart
    .map((item) => {
      const sub = item.subtotal || item.precio * item.cantidad;
      total += sub;
      const props = [];
      if (item.madera) props.push(`🪵 ${escapeHtml(item.madera)}`);
      if (item.tamano) props.push(`📐 ${escapeHtml(item.tamano)}`);
      const propsHtml = props.length ? `<span class="cart-item-props">${props.join(" · ")}</span>` : "";
      return `
        <div class="cart-item">
          <span class="cart-item-qty">${item.cantidad}x</span>
          <div class="cart-item-info">
            <span class="cart-item-name">${escapeHtml(item.producto)}</span>
            ${propsHtml}
          </div>
          <span class="cart-item-price">$${sub.toFixed(2)}</span>
        </div>`;
    })
    .join("");

  cartTotal?.classList.remove("hidden");
  if (cartTotalAmount) cartTotalAmount.textContent = `$${total.toFixed(2)}`;

  const landingCart = $("#chatbotCartSummary");
  if (landingCart) {
    landingCart.classList.remove("hidden");
    const countEl = $("#chatbotCartItemsCount");
    const totalEl = $("#chatbotCartTotalAmount");
    if (countEl) countEl.textContent = `${state.cart.length} servicio${state.cart.length !== 1 ? "s" : ""}`;
    if (totalEl) totalEl.textContent = `$${total.toFixed(2)}`;
  }
}

async function handleSubmit(e) {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text || state.isLoading) return;

  // Require authentication before sending a message
  if (!state.auth?.token) {
    appendMessage("assistant", "⚠️ Debes iniciar sesión para usar el asistente de cotizaciones.", null, false);
    return;
  }

  if ($("#viewChat")) switchView("chat");
  welcomeCard.classList.add("hidden");
  appendMessage("user", text, null, false, new Date());
  messageInput.value = "";
  autoResizeTextarea();

  setLoading(true);
  const thinkingEl = showThinking(
    CONFIRMING_STATES.includes(state.conversationState)
      ? "Registrando pedido..."
      : "Pensando..."
  );

  try {
    const body = { message: text };
    if (state.conversationId) body.conversation_id = state.conversationId;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);

    const res = await apiFetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error en el servidor");
    }

    const data = await res.json();
    chatDebug("CHAT RESPONSE:", data);
    thinkingEl.remove();
    await applyChatResponse(data);
  } catch (err) {
    thinkingEl.remove();
    const msg = err.name === "AbortError"
      ? "La respuesta está tardando demasiado. Por favor intenta de nuevo."
      : (err.message || "No se pudo conectar.");
    appendMessage("assistant", `⚠️ ${msg}`, null, false);
  } finally {
    setLoading(false);
  }
}

async function applyChatResponse(data) {
  if (!data || typeof data !== "object") {
    console.error("CHAT RESPONSE inválido:", data);
    return;
  }

  chatDebug("CHAT RESPONSE:", {
    conversation_id: data.conversation_id,
    response: data.response,
    conversation_state: data.conversation_state,
    tools_used: data.tools_used,
    cart_len: (data.cart || []).length,
  });

  state.conversationId = data.conversation_id;
  updateConversationIdDisplay();
  updateConversationStateDisplay(data.conversation_state);
  updateCart(data.cart || []);

  if (!state.titles[state.conversationId]) {
    const lastUser = messagesEl.querySelector(".message.user:last-child .message-content");
    if (lastUser) state.titles[state.conversationId] = truncate(lastUser.textContent, 40);
  }

  const assistantText = extractAssistantText(data);
  const tools = normalizeToolsUsed(data.tools_used);

  if (!assistantText) {
    console.warn("CHAT RESPONSE sin texto del asistente:", data);
  }

  await appendMessage("assistant", assistantText || "…", tools, true, new Date());

  if (data.order_card && (isCustomer() || isLandingPage())) {
    appendOrderConfirmationCard(data.order_card);
  }
  if (sidebarNav) await loadConversations();
}

function setLoading(loading) {
  state.isLoading = loading;
  btnSend.disabled = loading;
  messageInput.disabled = loading;
  btnMic.disabled = loading || !state.speechSupported;
}

async function deleteConversation(conversationId) {
  try {
    const res = await apiFetch(`/conversations/${conversationId}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "No se pudo eliminar la conversación");
    }
    if (state.conversationId === conversationId) {
      startNewConversation();
    }
    await loadConversations();
    showStatusBanner("Conversación eliminada", "success");
    setTimeout(hideStatusBanner, 2500);
  } catch (err) {
    showStatusBanner(err.message || "No se pudo eliminar la conversación", "warning");
  }
}

function showThinking(text = "Pensando...") {
  const el = document.createElement("div");
  el.className = "message assistant thinking-indicator";
  el.innerHTML = `
    <div class="message-avatar avatar-carpinteria">🪵</div>
    <div class="message-body">
      <div style="display:flex;align-items:center;gap:12px;padding:8px 0;">
        <div class="thinking-dots"><span></span><span></span><span></span></div>
        <span class="thinking-text">${escapeHtml(text)}</span>
      </div>
    </div>`;
  messagesEl.appendChild(el);
  scrollToBottom();
  return el;
}

function showStatusBanner(text, type = "info") {
  if (!statusBanner) return;
  statusBanner.textContent = text;
  statusBanner.className = `status-banner visible ${type}`;
}

function hideStatusBanner() {
  statusBanner?.classList.remove("visible");
}

function appendMessage(role, content, toolsUsed = null, animate = false, timestamp = null) {
  if (!messagesEl) {
    console.error("MESSAGE RENDER: #messages no encontrado en el DOM");
    return Promise.resolve();
  }

  const safeContent = extractAssistantText(
    typeof content === "string" || content == null ? { response: content } : content
  );

  const el = document.createElement("div");
  el.className = `message ${role}`;

  const avatarHtml =
    role === "user"
      ? `<div class="message-avatar avatar-user" title="Tú"><span>${getUserInitials()}</span></div>`
      : `<div class="message-avatar avatar-carpinteria" title="CarpinterÍA">🪵</div>`;

  const timeStr = formatTime(timestamp);
  const tools = normalizeToolsUsed(toolsUsed);
  const toolsHtml =
    role === "assistant" && tools.length
      ? `<div class="message-tools">${tools
          .map(
            (name) => `
          <span class="tool-badge tool-badge-${String(name).replace(/_/g, "-")}">
            <span class="tool-icon">⚙</span>
            ${escapeHtml(TOOL_LABELS[name] || name)}
          </span>`
          )
          .join("")}</div>`
      : "";

  el.innerHTML = `
    ${avatarHtml}
    <div class="message-body">
      <div class="message-meta">
        <span class="message-sender">${role === "user" ? escapeHtml(state.auth?.user?.full_name || "Tú") : "Carpintería IA"}</span>
        <span class="message-time">${timeStr}</span>
      </div>
      ${toolsHtml}
      <div class="message-content"></div>
    </div>`;

  messagesEl.appendChild(el);
  const contentEl = el.querySelector(".message-content");

  if (!contentEl) {
    console.error("MESSAGE RENDER: .message-content no creado");
    return Promise.resolve();
  }

  const textForRender = role === "user" ? String(content ?? "").trim() : safeContent;

  if (animate && role === "assistant" && textForRender) {
    return typeText(contentEl, textForRender).catch((err) => {
      console.error("MESSAGE RENDER: fallo typeText, usando render directo", err);
      renderMessageContent(contentEl, textForRender);
      scrollToBottom();
    });
  }

  renderMessageContent(contentEl, textForRender);
  scrollToBottom();
  return Promise.resolve();
}

async function typeText(element, text, speed = 14) {
  const session = ++state.typeSession;
  const safeText = String(text ?? "");
  element.textContent = "";

  if (!safeText) {
    renderMessageContent(element, "");
    return;
  }

  const cursor = document.createElement("span");
  cursor.className = "typing-cursor";
  element.appendChild(cursor);

  for (let i = 0; i < safeText.length; i++) {
    if (session !== state.typeSession) {
      cursor.remove();
      return;
    }
    cursor.before(safeText[i]);
    if (i % 3 === 0) scrollToBottom();
    await sleep(speed);
  }

  if (session === state.typeSession) {
    cursor.remove();
    chatDebug("MESSAGE RENDER:", safeText.slice(0, 120));
    scrollToBottom();
  }
}

function scrollToBottom() {
  if (chatArea) chatArea.scrollTop = chatArea.scrollHeight;
}

function formatDate(iso) {
  const d = new Date(iso);
  const now = new Date();
  const diff = now - d;
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (mins < 1) return "ahora";
  if (mins < 60) return `hace ${mins}m`;
  if (hours < 24) return `hace ${hours}h`;
  if (days < 7) return `hace ${days}d`;
  return d.toLocaleDateString("es", { day: "numeric", month: "short" });
}

function truncate(str, len) {
  return str.length > len ? str.slice(0, len) + "…" : str;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// Exponer para nav "Nuevo pedido" desde sidebar customer
window.startNewConversation = startNewConversation;

// Botón nuevo chat en nav customer
document.addEventListener("DOMContentLoaded", () => {
  setTimeout(() => {
    const chatNav = sidebarNav?.querySelector('[data-view="chat"]');
    if (chatNav && isCustomer()) {
      chatNav.addEventListener("click", startNewConversation);
    }
  }, 0);
});

// ── CRUD Tipos de Madera ─────────────────────────────────────────────────────

async function loadWoodTypes() {
  const el = $("#woodTypesTable");
  if (!el) return;
  el.innerHTML = '<div class="loading-inline">Cargando tipos de madera...</div>';
  try {
    const res = await apiFetch("/admin/wood-types");
    const types = await res.json();
    if (!types.length) {
      el.innerHTML = '<p class="empty-msg">Sin tipos de madera configurados.</p>';
      return;
    }
    el.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>Estado</th>
            <th>Nombre</th>
            <th>Modificador</th>
            <th>Efecto en precio</th>
            <th>Descripción</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>${types
          .map((t) => {
            const pct = ((t.price_modifier - 1) * 100).toFixed(0);
            const effect = t.price_modifier === 1.0 ? "Base" : (t.price_modifier > 1 ? `+${pct}%` : `${pct}%`);
            return `
          <tr data-wood-id="${t.id}">
            <td>
              <label class="toggle-switch">
                <input type="checkbox" class="wood-active" ${t.active ? "checked" : ""} onchange="toggleWoodTypeActive(${t.id}, this.checked)">
                <span class="toggle-slider"></span>
              </label>
            </td>
            <td><strong>${escapeHtml(t.name)}</strong></td>
            <td><code>${t.price_modifier}x</code></td>
            <td><span class="wood-effect ${t.price_modifier > 1 ? 'premium' : t.price_modifier < 1 ? 'discount' : 'base'}">${effect}</span></td>
            <td class="wood-desc">${escapeHtml(t.description || "—")}</td>
            <td>
              <button type="button" class="btn-sm btn-save" onclick="editWoodType(${t.id}, ${t.price_modifier}, '${escapeHtml(t.description || "")}', ${t.active})">Editar</button>
              <button type="button" class="btn-sm btn-danger" onclick="deleteWoodType(${t.id}, '${escapeHtml(t.name)}')">Desactivar</button>
            </td>
          </tr>`;
          })
          .join("")}
        </tbody>
      </table>`;
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

function showNewWoodTypeModal() {
  const modal = $("#woodTypeModal");
  if (!modal) return;
  $("#woodTypeModalTitle").textContent = "Nuevo Tipo de Madera";
  $("#woodTypeId").value = "";
  $("#woodTypeName").value = "";
  $("#woodTypeModifier").value = "";
  $("#woodTypeDescription").value = "";
  $("#woodTypeActive").checked = true;
  modal.classList.remove("hidden");
}

function editWoodType(id, modifier, description, active) {
  const modal = $("#woodTypeModal");
  if (!modal) return;
  $("#woodTypeModalTitle").textContent = "Editar Tipo de Madera";
  $("#woodTypeId").value = id;
  $("#woodTypeName").value = "";
  $("#woodTypeModifier").value = modifier;
  $("#woodTypeDescription").value = description;
  $("#woodTypeActive").checked = active;
  modal.classList.remove("hidden");
}

function closeWoodTypeModal() {
  const modal = $("#woodTypeModal");
  if (modal) modal.classList.add("hidden");
}

async function handleSaveWoodType(e) {
  e.preventDefault();
  const id = $("#woodTypeId").value;
  const name = $("#woodTypeName").value.trim();
  const modifier = parseFloat($("#woodTypeModifier").value);
  const description = $("#woodTypeDescription").value.trim();
  const active = $("#woodTypeActive").checked;

  if (!name && !id) {
    showStatusBanner("El nombre es obligatorio", "warning");
    return;
  }
  if (isNaN(modifier) || modifier <= 0) {
    showStatusBanner("El modificador debe ser mayor a 0", "warning");
    return;
  }

  try {
    let res;
    if (id) {
      res = await apiFetch(`/admin/wood-types/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ price_modifier: modifier, description, active }),
      });
    } else {
      res = await apiFetch("/admin/wood-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, price_modifier: modifier, description }),
      });
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Error al guardar");
    }
    closeWoodTypeModal();
    showStatusBanner(id ? "Tipo de madera actualizado" : "Tipo de madera creado", "success");
    loadWoodTypes();
  } catch (err) {
    showStatusBanner(err.message, "warning");
  }
}

async function toggleWoodTypeActive(id, active) {
  try {
    const res = await apiFetch(`/admin/wood-types/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    });
    if (!res.ok) throw new Error("Error al actualizar");
    showStatusBanner(active ? "Tipo de madera activado" : "Tipo de madera desactivado", "success");
  } catch (err) {
    showStatusBanner(err.message, "warning");
    loadWoodTypes();
  }
}

async function deleteWoodType(id, name) {
  if (!confirm(`¿Desactivar el tipo de madera "${name}"?`)) return;
  try {
    const res = await apiFetch(`/admin/wood-types/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Error al desactivar");
    showStatusBanner(`"${name}" desactivado`, "success");
    loadWoodTypes();
  } catch (err) {
    showStatusBanner(err.message, "warning");
  }
}

// ── CRUD Tamaños de Producto ──────────────────────────────────────────────────

let currentSizesProductId = null;
let currentSizesProductName = "";

function showSizesModal(productId, productName) {
  currentSizesProductId = productId;
  currentSizesProductName = productName;
  const modal = $("#sizesModal");
  if (!modal) return;
  $("#sizesModalTitle").textContent = `Tamaños: ${productName}`;
  modal.classList.remove("hidden");
  loadProductSizes(productId);
}

function closeSizesModal() {
  const modal = $("#sizesModal");
  if (modal) modal.classList.add("hidden");
  currentSizesProductId = null;
}

async function loadProductSizes(productId) {
  const tbody = $("#sizesModalTableBody");
  if (!tbody) return;
  try {
    const res = await apiFetch(`/admin/products/${productId}/sizes`);
    const sizes = await res.json();
    if (!sizes.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-msg">Sin tamaños configurados</td></tr>';
      return;
    }
    tbody.innerHTML = sizes
      .map((s) => `
        <tr>
          <td><strong>${escapeHtml(s.size_label)}</strong></td>
          <td>${escapeHtml(s.dimensions || "—")}</td>
          <td><code>${s.price_modifier}x</code></td>
          <td>
            <button type="button" class="btn-sm btn-danger" onclick="handleDeleteSize(${s.id})">Eliminar</button>
          </td>
        </tr>`)
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-msg">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function handleCreateSize(e) {
  e.preventDefault();
  if (!currentSizesProductId) return;
  const label = $("#newSizeLabel").value.trim();
  const dims = $("#newSizeDims").value.trim();
  const modifier = parseFloat($("#newSizeModifier").value);

  if (!label) {
    showStatusBanner("El nombre del tamaño es obligatorio", "warning");
    return;
  }
  if (isNaN(modifier) || modifier <= 0) {
    showStatusBanner("El modificador debe ser mayor a 0", "warning");
    return;
  }

  try {
    const res = await apiFetch(`/admin/products/${currentSizesProductId}/sizes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ size_label: label, dimensions: dims || null, price_modifier: modifier }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Error al crear tamaño");
    }
    $("#newSizeLabel").value = "";
    $("#newSizeDims").value = "";
    $("#newSizeModifier").value = "";
    showStatusBanner("Tamaño creado", "success");
    loadProductSizes(currentSizesProductId);
  } catch (err) {
    showStatusBanner(err.message, "warning");
  }
}

async function handleDeleteSize(sizeId) {
  if (!confirm("¿Eliminar este tamaño?")) return;
  try {
    const res = await apiFetch(`/admin/products/sizes/${sizeId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Error al eliminar");
    showStatusBanner("Tamaño eliminado", "success");
    loadProductSizes(currentSizesProductId);
  } catch (err) {
    showStatusBanner(err.message, "warning");
  }
}

// ── Productos: tabla mejorada con rango de precios y botón de tamaños ────────

async function loadProducts() {
  const el = $("#productsTable");
  el.innerHTML = '<div class="loading-inline">Cargando productos...</div>';
  try {
    const catalogRes = await apiFetch("/catalog/full");
    const catalogData = await catalogRes.json();
    const products = catalogData.productos || [];
    const woodTypes = catalogData.tipos_madera || [];

    if (!products.length) {
      el.innerHTML = '<p class="empty-msg">Sin productos.</p>';
      return;
    }

    const invRes = await apiFetch("/admin/products");
    const invData = await invRes.json();
    const inventory = invData.productos || [];

    el.innerHTML = `
      <div class="products-summary" style="margin-bottom: 1rem; padding: 1rem; background: var(--bg-card, #f8f9fa); border-radius: 8px; display: flex; gap: 2rem; flex-wrap: wrap;">
        <div><strong>${products.length}</strong> productos activos</div>
        <div><strong>${woodTypes.length}</strong> tipos de madera</div>
        <div>Rangos de precio: <em>desde madera más económica hasta la más premium</em></div>
      </div>
      <table class="data-table products-table">
        <thead>
          <tr>
            <th>Activo</th>
            <th>Producto</th>
            <th>Stock</th>
            <th>Precio Base</th>
            <th>Rango de Precios</th>
            <th>Categoría</th>
            <th>Tamaños</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${products
          .map((p) => {
            const inv = inventory.find((i) => (i.id || i.id) === p.id) || {};
            const sizeCount = (p.tamanos || []).length;
            const priceDisplay = p.precio_minimo !== p.precio_maximo
              ? `<span class="price-range">$${p.precio_minimo.toFixed(0)} - $${p.precio_maximo.toFixed(0)}</span>`
              : `$${p.precio_base.toFixed(2)}`;
            return `
          <tr data-product-id="${p.id}">
            <td>
              <label class="toggle-switch">
                <input type="checkbox" class="product-active" ${(inv.activo || inv.menu_visible) ? "checked" : ""}>
                <span class="toggle-slider"></span>
              </label>
            </td>
            <td>
              <strong>${escapeHtml(p.nombre)}</strong>
              <div class="product-base-price">Base: $${p.precio_base.toFixed(2)}</div>
            </td>
            <td><input type="number" class="inline-input product-stock" min="0" step="1" value="${inv.stock || 0}"></td>
            <td><input type="number" class="inline-input product-price" min="0" step="0.5" value="${p.precio_base}"></td>
            <td>${priceDisplay}</td>
            <td><span class="category-badge">${escapeHtml(p.categoria || "—")}</span></td>
            <td>
              <button type="button" class="btn-sm btn-outline" onclick="showSizesModal(${p.id}, '${escapeHtml(p.nombre)}')">
                📐 ${sizeCount} tamaño${sizeCount !== 1 ? "s" : ""}
              </button>
            </td>
            <td><button type="button" class="btn-sm btn-save product-save">Guardar</button></td>
          </tr>`;
          })
          .join("")}
        </tbody>
      </table>`;

    el.querySelectorAll("tr[data-product-id]").forEach((row) => {
      const saveBtn = row.querySelector(".product-save");
      const activeToggle = row.querySelector(".product-active");
      const save = () => saveProductRow(row);
      saveBtn.addEventListener("click", save);
      activeToggle.addEventListener("change", save);
    });
  } catch (err) {
    el.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}
