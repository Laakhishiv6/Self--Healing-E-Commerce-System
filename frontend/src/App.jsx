import { useState, useEffect, useCallback } from "react";

const API_URL = "http://localhost:8001";
const fmt = (n) => `$${Number(n).toFixed(2)}`;
const CATEGORIES = ["Electronics","Footwear","Kitchen","Fitness","Home","Clothing","Books","Sports","General"];

const CATEGORY_IMG = {
  Electronics: "https://images.unsplash.com/photo-1498049794561-7780e7231661?w=500&h=300&fit=crop&auto=format",
  Footwear:    "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=500&h=300&fit=crop&auto=format",
  Kitchen:     "https://images.unsplash.com/photo-1447933601403-0c6688de566e?w=500&h=300&fit=crop&auto=format",
  Fitness:     "https://images.unsplash.com/photo-1575052814086-f385e2e2ad1b?w=500&h=300&fit=crop&auto=format",
  Home:        "https://images.unsplash.com/photo-1513694203232-719a280e022f?w=500&h=300&fit=crop&auto=format",
  Clothing:    "https://images.unsplash.com/photo-1523381210434-271e8be1f52b?w=500&h=300&fit=crop&auto=format",
  Books:       "https://images.unsplash.com/photo-1544947950-fa07a98d237f?w=500&h=300&fit=crop&auto=format",
  Sports:      "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=500&h=300&fit=crop&auto=format",
  General:     "https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=500&h=300&fit=crop&auto=format",
};

function Stars({ id }) {
  const r = 3 + ((id * 13) % 20) / 10;
  return (
    <div style={{ display:"flex", alignItems:"center", gap:3 }}>
      {[1,2,3,4,5].map(i => (
        <span key={i} style={{ fontSize:13, color: i<=Math.round(r) ? "#f59e0b" : "#d1d5db" }}>★</span>
      ))}
      <span style={{ fontSize:12, color:"#94a3b8", marginLeft:2 }}>{r.toFixed(1)}</span>
    </div>
  );
}

function Modal({ title, onClose, children, width = 480 }) {
  return (
    <div style={{
      position:"fixed", inset:0, background:"rgba(15,23,42,0.55)",
      display:"flex", alignItems:"center", justifyContent:"center",
      zIndex:1000, padding:16, backdropFilter:"blur(3px)",
    }} onClick={onClose}>
      <div style={{
        background:"#fff", borderRadius:20, padding:32,
        width:"100%", maxWidth:width, maxHeight:"92vh", overflowY:"auto",
        boxShadow:"0 24px 64px rgba(0,0,0,0.2)",
        animation:"popUp .18s ease-out",
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:24 }}>
          <h2 style={{ fontSize:19, fontWeight:800, color:"#0f172a" }}>{title}</h2>
          <button onClick={onClose} style={{
            background:"#f1f5f9", border:"none", borderRadius:8,
            width:34, height:34, cursor:"pointer", fontSize:20, color:"#64748b",
            display:"flex", alignItems:"center", justifyContent:"center",
          }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom:16 }}>
      <label style={{ display:"block", fontSize:13, fontWeight:600, color:"#374151", marginBottom:6 }}>
        {label}
      </label>
      {children}
    </div>
  );
}

export default function App() {
  const [products, setProducts]   = useState([]);
  const [serviceUp, setServiceUp] = useState(true);
  const [cart, setCart]           = useState([]);   // [{product, qty}]
  const [cartOpen, setCartOpen]   = useState(false);
  const [modal, setModal]         = useState(null); // null | {type}
  const [loading, setLoading]     = useState(false);
  const [toast, setToast]         = useState(null);

  // product form
  const [form, setForm] = useState({ name:"", price:"", stock:"", category:"General" });

  // checkout state
  const [checkoutStep, setCheckoutStep] = useState(1); // 1=details 2=payment 3=success
  const [customerName, setCustomerName] = useState("");
  const [cardLast4, setCardLast4]       = useState("");
  const [paymentResult, setPaymentResult] = useState(null);

  const cartCount = cart.reduce((s, i) => s + i.qty, 0);
  const cartTotal = cart.reduce((s, i) => s + i.product.price * i.qty, 0);

  const showToast = useCallback((msg, type = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  }, []);

  const loadProducts = useCallback(() => {
    fetch(`${API_URL}/products`).then(r => r.json()).then(d => setProducts(d.products || [])).catch(() => {});
  }, []);

  useEffect(() => {
    loadProducts();
    const t = setInterval(loadProducts, 8000);
    return () => clearInterval(t);
  }, [loadProducts]);

  useEffect(() => {
    const poll = async () => {
      try { const r = await fetch(`${API_URL}/health`); setServiceUp(r.ok); } catch { setServiceUp(false); }
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => clearInterval(t);
  }, []);

  // ── Cart ──────────────────────────────────────────────────────────────────────
  const addToCart = (product) => {
    setCart(prev => {
      const exists = prev.find(i => i.product.id === product.id);
      if (exists) return prev.map(i => i.product.id === product.id ? { ...i, qty: i.qty + 1 } : i);
      return [...prev, { product, qty: 1 }];
    });
    showToast(`${product.name} added to cart`);
  };

  const updateQty = (productId, delta) => {
    setCart(prev => prev
      .map(i => i.product.id === productId ? { ...i, qty: Math.max(0, i.qty + delta) } : i)
      .filter(i => i.qty > 0)
    );
  };

  const removeFromCart = (productId) => setCart(prev => prev.filter(i => i.product.id !== productId));

  // ── Checkout ─────────────────────────────────────────────────────────────────
  const openCheckout = () => {
    setCheckoutStep(1);
    setCustomerName("");
    setCardLast4("");
    setPaymentResult(null);
    setModal({ type: "checkout" });
  };

  const placeOrdersAndPay = async () => {
    if (!customerName.trim() || !cardLast4.trim()) return;
    setLoading(true);
    try {
      // Create one order per cart item
      const orderPromises = cart.map(item =>
        fetch(`${API_URL}/orders`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            product_id:    item.product.id,
            quantity:      item.qty,
            customer_name: customerName.trim(),
          }),
        }).then(r => r.json())
      );
      const orders = await Promise.all(orderPromises);
      const firstOrderId = orders[0]?.order_id;

      // One payment for the total
      const payRes = await fetch(`${API_URL}/payments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          order_id:   firstOrderId,
          amount:     parseFloat(cartTotal.toFixed(2)),
          card_last4: cardLast4.trim().slice(-4),
        }),
      });

      if (!payRes.ok) {
        const err = await payRes.json();
        throw new Error(err.detail || "Payment failed");
      }

      const payment = await payRes.json();
      setPaymentResult(payment);
      setCheckoutStep(3);
      setCart([]);
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setLoading(false);
    }
  };

  // ── Product CRUD ──────────────────────────────────────────────────────────────
  const openAddProduct = () => {
    setForm({ name:"", price:"", stock:"", category:"General" });
    setModal({ type: "add-product" });
  };

  const openEditProduct = (p) => {
    setForm({ name:p.name, price:p.price, stock:p.stock, category:p.category });
    setModal({ type:"edit-product", data:p });
  };

  const saveProduct = async () => {
    if (!form.name.trim() || !form.price) return;
    setLoading(true);
    const body = { name:form.name.trim(), price:parseFloat(form.price), stock:parseInt(form.stock)||0, category:form.category };
    const isEdit = modal.type === "edit-product";
    try {
      const r = await fetch(
        isEdit ? `${API_URL}/products/${modal.data.id}` : `${API_URL}/products`,
        { method: isEdit ? "PUT" : "POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) }
      );
      if (!r.ok) throw new Error((await r.json()).detail || "Failed");
      showToast(`"${body.name}" ${isEdit ? "updated" : "added"}`);
      loadProducts(); setModal(null);
    } catch(e) { showToast(e.message,"error"); }
    finally { setLoading(false); }
  };

  const deleteProduct = async () => {
    setLoading(true);
    try {
      await fetch(`${API_URL}/products/${modal.data.id}`, { method:"DELETE" });
      showToast(`"${modal.data.name}" removed`);
      loadProducts(); setModal(null);
    } catch(e) { showToast(e.message,"error"); }
    finally { setLoading(false); }
  };

  return (
    <div style={{ minHeight:"100vh", background:"#f1f5f9" }}>
      <style>{`
        @keyframes fadeUp   { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
        @keyframes slideDown{ from{opacity:0;transform:translateY(-10px)} to{opacity:1;transform:translateY(0)} }
        @keyframes slideIn  { from{transform:translateX(100%)} to{transform:translateX(0)} }
        @keyframes popUp    { from{opacity:0;transform:scale(0.96)} to{opacity:1;transform:scale(1)} }
        @keyframes pulse    { 0%,100%{opacity:1} 50%{opacity:0.4} }

        .product-card {
          background:#fff; border-radius:18px; overflow:hidden;
          box-shadow:0 2px 8px rgba(0,0,0,0.07);
          transition:box-shadow .22s, transform .22s;
        }
        .product-card:hover { box-shadow:0 12px 32px rgba(99,102,241,0.13); transform:translateY(-4px); }

        .btn {
          cursor:pointer; border:none; border-radius:10px;
          font-size:13px; font-weight:700; padding:10px 20px;
          transition:all .15s; display:inline-flex;
          align-items:center; justify-content:center; gap:6px;
          white-space:nowrap; font-family:inherit;
        }
        .btn:active:not(:disabled){ transform:scale(0.97); }
        .btn:disabled{ opacity:0.45; cursor:not-allowed; }
        .btn-primary{ background:#6366f1; color:#fff; }
        .btn-primary:hover:not(:disabled){ background:#4f46e5; }
        .btn-success{ background:#16a34a; color:#fff; }
        .btn-success:hover:not(:disabled){ background:#15803d; }
        .btn-danger{ background:#fef2f2; color:#ef4444; border:1.5px solid #fecaca; }
        .btn-danger:hover:not(:disabled){ background:#fee2e2; }
        .btn-ghost{ background:#f8fafc; color:#475569; border:1.5px solid #e2e8f0; }
        .btn-ghost:hover:not(:disabled){ background:#f1f5f9; color:#0f172a; }

        input, select {
          background:#f8fafc; border:1.5px solid #e2e8f0;
          color:#0f172a; border-radius:10px; padding:10px 14px;
          font-size:13px; outline:none; width:100%;
          transition:border-color .15s; font-family:inherit; box-sizing:border-box;
        }
        input:focus, select:focus { border-color:#6366f1; background:#fff; box-shadow:0 0 0 3px rgba(99,102,241,0.1); }
        input::placeholder { color:#94a3b8; }
      `}</style>

      {/* Toast */}
      {toast && (
        <div style={{
          position:"fixed", top:20, right:20, zIndex:9999,
          background: toast.type==="error" ? "#fef2f2" : "#f0fdf4",
          border:`1.5px solid ${toast.type==="error" ? "#fca5a5" : "#86efac"}`,
          color: toast.type==="error" ? "#dc2626" : "#16a34a",
          padding:"12px 20px", borderRadius:12,
          fontSize:13, fontWeight:600,
          boxShadow:"0 8px 24px rgba(0,0,0,0.12)",
          animation:"slideDown .2s",
          display:"flex", alignItems:"center", gap:8, maxWidth:320,
        }}>
          <span style={{ fontSize:16 }}>{toast.type==="error" ? "✕" : "✓"}</span>
          {toast.msg}
        </div>
      )}

      {/* ── HEADER ──────────────────────────────────────────────────────────── */}
      <header style={{
        background:"#fff", borderBottom:"1px solid #e2e8f0",
        position:"sticky", top:0, zIndex:100,
        boxShadow:"0 1px 6px rgba(0,0,0,0.06)",
      }}>
        <div style={{
          maxWidth:1200, margin:"0 auto", padding:"0 24px", height:66,
          display:"flex", alignItems:"center", justifyContent:"space-between", gap:16,
        }}>
          {/* Logo */}
          <div style={{ display:"flex", alignItems:"center", gap:12, flexShrink:0 }}>
            <div style={{
              width:40, height:40, borderRadius:12,
              background:"linear-gradient(135deg,#6366f1,#8b5cf6)",
              display:"flex", alignItems:"center", justifyContent:"center",
              fontSize:20, boxShadow:"0 4px 12px rgba(99,102,241,0.35)",
            }}>🛍️</div>
            <div>
              <div style={{ fontSize:17, fontWeight:900, color:"#0f172a", letterSpacing:-0.5, lineHeight:1 }}>ShopCore</div>
              <div style={{ fontSize:10, color:"#94a3b8", letterSpacing:0.5 }}>E-Commerce Store</div>
            </div>
          </div>

          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            {/* Health badge */}
            <div style={{
              display:"flex", alignItems:"center", gap:6,
              padding:"6px 14px", borderRadius:20,
              background: serviceUp ? "#f0fdf4" : "#fef2f2",
              border:`1px solid ${serviceUp ? "#86efac" : "#fca5a5"}`,
              color: serviceUp ? "#16a34a" : "#dc2626",
              fontSize:12, fontWeight:700,
            }}>
              <span style={{
                width:7, height:7, borderRadius:"50%",
                background: serviceUp ? "#22c55e" : "#ef4444",
                animation: serviceUp ? "pulse 2s infinite" : "none",
              }}/>
              {serviceUp ? "Online" : "Degraded"}
            </div>

            {/* Add product */}
            <button className="btn btn-ghost" onClick={openAddProduct}
              style={{ fontSize:13, padding:"8px 16px" }}>
              + Add Product
            </button>

            {/* Cart button */}
            <button className="btn btn-primary" onClick={() => setCartOpen(true)}
              style={{ fontSize:14, padding:"9px 20px", position:"relative" }}>
              🛒 Cart
              {cartCount > 0 && (
                <span style={{
                  position:"absolute", top:-8, right:-8,
                  background:"#ef4444", color:"#fff",
                  borderRadius:"50%", width:20, height:20,
                  fontSize:11, fontWeight:800,
                  display:"flex", alignItems:"center", justifyContent:"center",
                  border:"2px solid #fff",
                }}>{cartCount}</span>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* ── MAIN ─────────────────────────────────────────────────────────────── */}
      <main style={{ maxWidth:1200, margin:"0 auto", padding:"36px 24px" }}>

        {/* Hero banner */}
        <div style={{
          borderRadius:20, marginBottom:36,
          background:"linear-gradient(135deg,#6366f1 0%,#8b5cf6 50%,#a78bfa 100%)",
          padding:"36px 40px",
          display:"flex", justifyContent:"space-between", alignItems:"center",
          boxShadow:"0 8px 32px rgba(99,102,241,0.3)",
          flexWrap:"wrap", gap:20,
        }}>
          <div>
            <div style={{ fontSize:28, fontWeight:900, color:"#fff", marginBottom:8, letterSpacing:-0.5 }}>
              Welcome to ShopCore
            </div>
            <div style={{ fontSize:15, color:"rgba(255,255,255,0.82)" }}>
              {products.length} products available — add items to cart and checkout
            </div>
          </div>
          {cartCount > 0 && (
            <button className="btn" onClick={() => setCartOpen(true)}
              style={{ background:"#fff", color:"#6366f1", fontSize:14, padding:"12px 28px", fontWeight:800 }}>
              View Cart ({cartCount}) — {fmt(cartTotal)}
            </button>
          )}
        </div>

        {/* Products heading */}
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:20 }}>
          <h2 style={{ fontSize:20, fontWeight:800, color:"#0f172a" }}>
            All Products
            <span style={{ fontSize:14, fontWeight:500, color:"#94a3b8", marginLeft:10 }}>
              ({products.length})
            </span>
          </h2>
        </div>

        {/* Products grid */}
        {products.length === 0 ? (
          <div style={{
            textAlign:"center", padding:"80px 0",
            background:"#fff", borderRadius:20,
            boxShadow:"0 2px 8px rgba(0,0,0,0.06)",
          }}>
            <div style={{ fontSize:64, marginBottom:16 }}>🏪</div>
            <h3 style={{ fontSize:20, fontWeight:700, color:"#0f172a", marginBottom:8 }}>No products yet</h3>
            <p style={{ color:"#64748b", marginBottom:28 }}>Add your first product to start selling</p>
            <button className="btn btn-primary" onClick={openAddProduct} style={{ fontSize:14, padding:"12px 28px" }}>
              + Add Product
            </button>
          </div>
        ) : (
          <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(260px,1fr))", gap:22, animation:"fadeUp .3s" }}>
            {products.map(p => (
              <div key={p.id} className="product-card">
                <div style={{ position:"relative", height:196, overflow:"hidden" }}>
                  <img
                    src={CATEGORY_IMG[p.category] || CATEGORY_IMG.General}
                    alt={p.name}
                    style={{ width:"100%", height:"100%", objectFit:"cover", display:"block" }}
                    onError={e => { e.target.src = CATEGORY_IMG.General; }}
                  />
                  <span style={{
                    position:"absolute", top:12, left:12,
                    background:"rgba(255,255,255,0.93)", color:"#6366f1",
                    padding:"3px 11px", borderRadius:20, fontSize:11, fontWeight:700,
                  }}>{p.category}</span>

                  {/* Admin icons */}
                  <div style={{ position:"absolute", top:10, right:10, display:"flex", gap:6 }}>
                    <button onClick={() => openEditProduct(p)} style={{
                      background:"rgba(255,255,255,0.9)", border:"none", borderRadius:8,
                      width:30, height:30, cursor:"pointer", fontSize:14,
                      display:"flex", alignItems:"center", justifyContent:"center",
                    }} title="Edit">✏️</button>
                    <button onClick={() => setModal({ type:"delete-product", data:p })} style={{
                      background:"rgba(255,255,255,0.9)", border:"none", borderRadius:8,
                      width:30, height:30, cursor:"pointer", fontSize:14,
                      display:"flex", alignItems:"center", justifyContent:"center",
                    }} title="Delete">🗑️</button>
                  </div>

                  {p.stock === 0 && (
                    <div style={{
                      position:"absolute", inset:0, background:"rgba(0,0,0,0.45)",
                      display:"flex", alignItems:"center", justifyContent:"center",
                    }}>
                      <span style={{ background:"#fff", color:"#ef4444", padding:"6px 16px", borderRadius:8, fontWeight:800, fontSize:13 }}>
                        Out of Stock
                      </span>
                    </div>
                  )}
                </div>

                <div style={{ padding:18 }}>
                  <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:6, gap:8 }}>
                    <h3 style={{ fontSize:15, fontWeight:700, color:"#0f172a", lineHeight:1.3 }}>{p.name}</h3>
                    <span style={{ fontSize:18, fontWeight:900, color:"#6366f1", flexShrink:0 }}>{fmt(p.price)}</span>
                  </div>

                  <Stars id={p.id} />

                  <div style={{
                    fontSize:12, fontWeight:600, marginTop:8, marginBottom:14,
                    color: p.stock > 10 ? "#16a34a" : p.stock > 0 ? "#d97706" : "#ef4444",
                  }}>
                    {p.stock > 10 ? `✓ ${p.stock} in stock` : p.stock > 0 ? `⚡ Only ${p.stock} left` : "✕ Out of stock"}
                  </div>

                  <button
                    className="btn btn-primary"
                    style={{ width:"100%", padding:"10px", fontSize:14 }}
                    disabled={p.stock === 0}
                    onClick={() => addToCart(p)}
                  >
                    {cart.find(i => i.product.id === p.id)
                      ? `✓ In Cart (${cart.find(i => i.product.id === p.id).qty}) — Add More`
                      : "Add to Cart"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* ── CART DRAWER ─────────────────────────────────────────────────────── */}
      {cartOpen && (
        <div style={{
          position:"fixed", inset:0, zIndex:200,
          display:"flex", justifyContent:"flex-end",
        }}>
          {/* Backdrop */}
          <div style={{ flex:1, background:"rgba(15,23,42,0.4)" }} onClick={() => setCartOpen(false)} />

          {/* Drawer */}
          <div style={{
            width:420, maxWidth:"100vw", background:"#fff",
            boxShadow:"-8px 0 40px rgba(0,0,0,0.15)",
            display:"flex", flexDirection:"column",
            animation:"slideIn .25s ease-out",
          }}>
            {/* Drawer header */}
            <div style={{
              padding:"24px 24px 20px",
              borderBottom:"1px solid #e2e8f0",
              display:"flex", justifyContent:"space-between", alignItems:"center",
            }}>
              <div>
                <div style={{ fontSize:18, fontWeight:800, color:"#0f172a" }}>Your Cart</div>
                <div style={{ fontSize:13, color:"#94a3b8", marginTop:2 }}>
                  {cartCount} item{cartCount !== 1 ? "s" : ""}
                </div>
              </div>
              <button onClick={() => setCartOpen(false)} style={{
                background:"#f1f5f9", border:"none", borderRadius:10,
                width:36, height:36, cursor:"pointer", fontSize:20, color:"#64748b",
                display:"flex", alignItems:"center", justifyContent:"center",
              }}>×</button>
            </div>

            {/* Cart items */}
            <div style={{ flex:1, overflowY:"auto", padding:"16px 24px" }}>
              {cart.length === 0 ? (
                <div style={{ textAlign:"center", padding:"60px 0", color:"#94a3b8" }}>
                  <div style={{ fontSize:48, marginBottom:12 }}>🛒</div>
                  <div style={{ fontSize:15, fontWeight:600, color:"#64748b" }}>Your cart is empty</div>
                  <div style={{ fontSize:13, marginTop:6 }}>Add some products to get started</div>
                </div>
              ) : (
                <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
                  {cart.map(({ product: p, qty }) => (
                    <div key={p.id} style={{
                      display:"flex", gap:14, alignItems:"center",
                      padding:14, background:"#f8fafc", borderRadius:14,
                      border:"1px solid #e2e8f0",
                    }}>
                      <img
                        src={CATEGORY_IMG[p.category] || CATEGORY_IMG.General}
                        alt={p.name}
                        style={{ width:60, height:60, borderRadius:10, objectFit:"cover", flexShrink:0 }}
                        onError={e => { e.target.src = CATEGORY_IMG.General; }}
                      />
                      <div style={{ flex:1, minWidth:0 }}>
                        <div style={{ fontSize:14, fontWeight:700, color:"#0f172a", marginBottom:4, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                          {p.name}
                        </div>
                        <div style={{ fontSize:15, fontWeight:800, color:"#6366f1" }}>{fmt(p.price * qty)}</div>
                        <div style={{ fontSize:12, color:"#94a3b8" }}>{fmt(p.price)} each</div>
                      </div>
                      <div style={{ display:"flex", flexDirection:"column", alignItems:"center", gap:6 }}>
                        <div style={{ display:"flex", alignItems:"center", gap:0, background:"#e2e8f0", borderRadius:8, overflow:"hidden" }}>
                          <button onClick={() => updateQty(p.id, -1)} style={{
                            background:"transparent", border:"none", cursor:"pointer",
                            padding:"6px 10px", fontSize:16, fontWeight:700, color:"#374151",
                          }}>−</button>
                          <span style={{ fontSize:14, fontWeight:700, padding:"0 8px", minWidth:24, textAlign:"center" }}>{qty}</span>
                          <button onClick={() => updateQty(p.id, 1)} style={{
                            background:"transparent", border:"none", cursor:"pointer",
                            padding:"6px 10px", fontSize:16, fontWeight:700, color:"#374151",
                          }}>+</button>
                        </div>
                        <button onClick={() => removeFromCart(p.id)} style={{
                          background:"transparent", border:"none", cursor:"pointer",
                          fontSize:11, color:"#ef4444", fontWeight:600, padding:0,
                        }}>Remove</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Drawer footer */}
            {cart.length > 0 && (
              <div style={{ padding:"20px 24px", borderTop:"1px solid #e2e8f0" }}>
                <div style={{
                  display:"flex", justifyContent:"space-between", alignItems:"center",
                  marginBottom:16,
                }}>
                  <span style={{ fontSize:15, fontWeight:600, color:"#374151" }}>Total</span>
                  <span style={{ fontSize:24, fontWeight:900, color:"#0f172a" }}>{fmt(cartTotal)}</span>
                </div>
                <button className="btn btn-success" style={{ width:"100%", padding:"14px", fontSize:15 }}
                  onClick={() => { setCartOpen(false); openCheckout(); }}>
                  Checkout →
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── MODALS ──────────────────────────────────────────────────────────── */}

      {/* Add / Edit Product */}
      {(modal?.type === "add-product" || modal?.type === "edit-product") && (
        <Modal title={modal.type === "add-product" ? "Add New Product" : "Edit Product"} onClose={() => setModal(null)}>
          <Field label="Product Name *">
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name:e.target.value }))}
              placeholder="e.g. Wireless Keyboard" autoFocus />
          </Field>
          <Field label="Category">
            <select value={form.category} onChange={e => setForm(f => ({ ...f, category:e.target.value }))}>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </Field>
          <div style={{ borderRadius:12, overflow:"hidden", height:120, marginBottom:16 }}>
            <img src={CATEGORY_IMG[form.category] || CATEGORY_IMG.General}
              alt="preview" style={{ width:"100%", height:"100%", objectFit:"cover" }} />
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:14 }}>
            <Field label="Price ($) *">
              <input type="number" min="0" step="0.01" value={form.price}
                onChange={e => setForm(f => ({ ...f, price:e.target.value }))} placeholder="0.00" />
            </Field>
            <Field label="Stock Qty">
              <input type="number" min="0" value={form.stock}
                onChange={e => setForm(f => ({ ...f, stock:e.target.value }))} placeholder="0" />
            </Field>
          </div>
          <div style={{ display:"flex", gap:10, marginTop:8 }}>
            <button className="btn btn-primary" onClick={saveProduct}
              disabled={loading || !form.name.trim() || !form.price}
              style={{ flex:1, padding:"12px", fontSize:14 }}>
              {loading ? "Saving…" : modal.type === "add-product" ? "Add to Catalog" : "Save Changes"}
            </button>
            <button className="btn btn-ghost" onClick={() => setModal(null)} style={{ padding:"12px 20px" }}>Cancel</button>
          </div>
        </Modal>
      )}

      {/* Delete Product */}
      {modal?.type === "delete-product" && (
        <Modal title="Remove Product" onClose={() => setModal(null)}>
          <div style={{ textAlign:"center", padding:"8px 0 24px" }}>
            <div style={{
              width:64, height:64, background:"#fef2f2", borderRadius:"50%",
              display:"flex", alignItems:"center", justifyContent:"center",
              fontSize:28, margin:"0 auto 16px",
            }}>🗑️</div>
            <p style={{ fontSize:15, color:"#374151", lineHeight:1.7 }}>
              Remove <strong>"{modal.data.name}"</strong> from the catalog?
            </p>
            <p style={{ fontSize:13, color:"#94a3b8", marginTop:6 }}>This cannot be undone.</p>
          </div>
          <div style={{ display:"flex", gap:10 }}>
            <button className="btn btn-danger" onClick={deleteProduct} disabled={loading}
              style={{ flex:1, padding:"12px", fontSize:14 }}>
              {loading ? "Removing…" : "Yes, Remove"}
            </button>
            <button className="btn btn-ghost" onClick={() => setModal(null)} style={{ padding:"12px 20px" }}>Cancel</button>
          </div>
        </Modal>
      )}

      {/* Checkout Modal — 3 steps */}
      {modal?.type === "checkout" && (
        <Modal title={
          checkoutStep === 1 ? "Checkout" :
          checkoutStep === 2 ? "Payment" : "Order Confirmed!"
        } onClose={checkoutStep === 3 ? () => setModal(null) : () => setModal(null)} width={520}>

          {/* Step indicator */}
          {checkoutStep < 3 && (
            <div style={{ display:"flex", gap:8, marginBottom:24 }}>
              {["Cart Review","Payment"].map((label, i) => (
                <div key={i} style={{ flex:1, textAlign:"center" }}>
                  <div style={{
                    height:4, borderRadius:4, marginBottom:6,
                    background: checkoutStep > i ? "#6366f1" : checkoutStep === i+1 ? "#6366f1" : "#e2e8f0",
                  }}/>
                  <div style={{ fontSize:11, fontWeight:600, color: checkoutStep === i+1 ? "#6366f1" : "#94a3b8" }}>
                    {label}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Step 1: Details */}
          {checkoutStep === 1 && (
            <>
              {/* Cart summary */}
              <div style={{ marginBottom:20 }}>
                {cart.map(({ product: p, qty }) => (
                  <div key={p.id} style={{
                    display:"flex", justifyContent:"space-between", alignItems:"center",
                    padding:"10px 0", borderBottom:"1px solid #f1f5f9",
                  }}>
                    <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                      <img src={CATEGORY_IMG[p.category]||CATEGORY_IMG.General} alt={p.name}
                        style={{ width:40, height:40, borderRadius:8, objectFit:"cover" }}
                        onError={e=>{e.target.src=CATEGORY_IMG.General;}} />
                      <div>
                        <div style={{ fontSize:14, fontWeight:600, color:"#0f172a" }}>{p.name}</div>
                        <div style={{ fontSize:12, color:"#94a3b8" }}>Qty: {qty}</div>
                      </div>
                    </div>
                    <div style={{ fontSize:15, fontWeight:700, color:"#6366f1" }}>{fmt(p.price * qty)}</div>
                  </div>
                ))}
                <div style={{
                  display:"flex", justifyContent:"space-between",
                  padding:"14px 0 0", fontWeight:800, fontSize:16, color:"#0f172a",
                }}>
                  <span>Total</span>
                  <span>{fmt(cartTotal)}</span>
                </div>
              </div>

              <Field label="Your Name *">
                <input value={customerName} onChange={e => setCustomerName(e.target.value)}
                  placeholder="Enter your name" autoFocus />
              </Field>

              <button className="btn btn-primary"
                disabled={!customerName.trim()}
                onClick={() => setCheckoutStep(2)}
                style={{ width:"100%", padding:"13px", fontSize:15, marginTop:8 }}>
                Continue to Payment →
              </button>
            </>
          )}

          {/* Step 2: Payment */}
          {checkoutStep === 2 && (
            <>
              <div style={{
                background:"#f8fafc", borderRadius:14, padding:"16px 20px", marginBottom:20,
                border:"1px solid #e2e8f0",
              }}>
                <div style={{ fontSize:13, color:"#64748b", marginBottom:4 }}>Ordering as</div>
                <div style={{ fontSize:16, fontWeight:700, color:"#0f172a" }}>{customerName}</div>
                <div style={{ fontSize:13, color:"#94a3b8", marginTop:6 }}>
                  {cartCount} item{cartCount !== 1 ? "s" : ""} · Total:{" "}
                  <strong style={{ color:"#6366f1" }}>{fmt(cartTotal)}</strong>
                </div>
              </div>

              <div style={{
                background:"#f8fafc", borderRadius:14, padding:"20px",
                marginBottom:20, border:"1px solid #e2e8f0",
              }}>
                <div style={{ fontSize:13, fontWeight:600, color:"#374151", marginBottom:12 }}>Card Details</div>
                <div style={{
                  background:"linear-gradient(135deg,#6366f1,#8b5cf6)",
                  borderRadius:12, padding:"20px 24px", marginBottom:16,
                  color:"#fff",
                }}>
                  <div style={{ fontSize:11, opacity:0.7, marginBottom:12, letterSpacing:1 }}>CREDIT / DEBIT CARD</div>
                  <div style={{ fontSize:20, letterSpacing:4, fontWeight:600, marginBottom:12 }}>
                    •••• •••• •••• {cardLast4 || "????"}
                  </div>
                  <div style={{ fontSize:13, opacity:0.8 }}>{customerName}</div>
                </div>
                <Field label="Last 4 digits of card *">
                  <input
                    value={cardLast4}
                    onChange={e => setCardLast4(e.target.value.replace(/\D/g,"").slice(0,4))}
                    placeholder="4242"
                    maxLength={4}
                    style={{ textAlign:"center", fontSize:22, fontWeight:700, letterSpacing:8 }}
                    autoFocus
                  />
                </Field>
              </div>

              <div style={{ display:"flex", gap:10 }}>
                <button className="btn btn-ghost" onClick={() => setCheckoutStep(1)} style={{ padding:"12px 20px" }}>
                  ← Back
                </button>
                <button className="btn btn-success"
                  disabled={loading || cardLast4.length !== 4}
                  onClick={placeOrdersAndPay}
                  style={{ flex:1, padding:"13px", fontSize:15 }}>
                  {loading ? "Processing…" : `Pay ${fmt(cartTotal)}`}
                </button>
              </div>
            </>
          )}

          {/* Step 3: Success */}
          {checkoutStep === 3 && (
            <div style={{ textAlign:"center", padding:"8px 0" }}>
              <div style={{
                width:80, height:80, background:"#f0fdf4", borderRadius:"50%",
                display:"flex", alignItems:"center", justifyContent:"center",
                fontSize:40, margin:"0 auto 20px",
              }}>✅</div>
              <h3 style={{ fontSize:22, fontWeight:900, color:"#0f172a", marginBottom:8 }}>
                Payment Successful!
              </h3>
              <p style={{ fontSize:15, color:"#64748b", marginBottom:20 }}>
                Thank you, <strong>{customerName}</strong>! Your order is confirmed.
              </p>

              {paymentResult && (
                <div style={{
                  background:"#f8fafc", borderRadius:14, padding:"16px 20px",
                  border:"1px solid #e2e8f0", marginBottom:24, textAlign:"left",
                }}>
                  {[
                    ["Payment ID",    `#${paymentResult.payment_id}`],
                    ["Amount Paid",   fmt(paymentResult.amount)],
                    ["Card",          `•••• ${paymentResult.card_last4}`],
                    ["Status",        paymentResult.status],
                  ].map(([label, value]) => (
                    <div key={label} style={{
                      display:"flex", justifyContent:"space-between",
                      padding:"7px 0", borderBottom:"1px solid #f1f5f9", fontSize:14,
                    }}>
                      <span style={{ color:"#64748b" }}>{label}</span>
                      <span style={{ fontWeight:700, color:"#0f172a" }}>{value}</span>
                    </div>
                  ))}
                </div>
              )}

              <button className="btn btn-primary" onClick={() => setModal(null)}
                style={{ width:"100%", padding:"13px", fontSize:15 }}>
                Continue Shopping
              </button>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
