import streamlit as st
import pandas as pd

st.set_page_config(page_title="XYZ Fulfillment Hub", page_icon="📦", layout="wide")

# Demo clock: fixed so the sample deadlines always make sense
NOW = pd.Timestamp("2026-10-03 14:00")
STAGES = ["Received", "Processing", "Picking", "Packing", "Staged", "Shipped"]
OPEN_STAGES = ["Received", "Processing", "Picking", "Blocked"]  # stock still needed from main warehouse

st.markdown("""
<style>
.step{display:inline-block;padding:10px 16px;border-radius:8px;background:#e3f0ff;color:#0b3d91;
      font-weight:600;text-align:center;min-width:110px;margin:2px}
.step.done{background:#dff5e1;color:#14632b}
.arrow{font-size:22px;color:#888;margin:0 4px}
</style>
""", unsafe_allow_html=True)

# ---------------- DATA (kept in session so buttons can change it) ----------------
if "orders" not in st.session_state:
    o = pd.read_csv("orders.csv", parse_dates=["deadline"])
    o["block_reason"] = o["block_reason"].fillna("")
    st.session_state.orders = o
    st.session_state.inventory = pd.read_csv("inventory.csv")
    st.session_state.staging = pd.read_csv("staging.csv", parse_dates=["pickup_deadline"])
    st.session_state.exceptions = pd.read_csv("exceptions.csv")


def get_inventory():
    inv = st.session_state.inventory.copy()
    inv["system_total"] = inv["main_stock"] + inv["secondary_stock"]
    # usable stock in main = physical count if counted, otherwise the system number
    inv["avail_main"] = inv["physical_main"].fillna(inv["main_stock"]).astype(int)

    def check(r):
        if pd.isna(r["physical_main"]):
            return "⚪ Not counted"
        d = int(r["physical_main"] - r["main_stock"])
        return "✅ Verified" if d == 0 else f"🟠 Mismatch ({d:+d})"

    inv["check"] = inv.apply(check, axis=1)
    return inv


def make_alert(r):
    if r["stock_short"]:
        return f"🔴 Short in main: need {r['qty']}, have {r['avail_main']}"
    if r["stage"] == "Blocked":
        return "🔴 " + (r["block_reason"] or "Blocked")
    if r["is_priority"] and r["stage"] != "Shipped":
        if r["mins_left"] < 0:
            return "🔴 SHIP-BY DEADLINE PASSED"
        if r["mins_left"] <= 90:
            return f"🟠 Ship-by in {int(r['mins_left'])} min"
    return ""


def get_orders():
    inv = get_inventory()
    o = st.session_state.orders.merge(
        inv[["sku", "product", "variant", "avail_main", "secondary_stock"]], on="sku", how="left")
    o["stock_short"] = o["stage"].isin(OPEN_STAGES) & (o["avail_main"] < o["qty"])
    o["status"] = o["stage"]
    o.loc[o["stock_short"], "status"] = "Blocked"
    o["mins_left"] = (o["deadline"] - NOW).dt.total_seconds() / 60
    o["is_priority"] = o["priority"] == "Yes"
    o["alert"] = o.apply(make_alert, axis=1)
    return o


def pickup_flag(r):
    if r["pickup_status"] == "Collected":
        return "✅ Collected"
    mins = (r["pickup_deadline"] - NOW).total_seconds() / 60
    if mins < 0:
        return "🔴 MISSED"
    if mins <= 60:
        return "🟠 DUE SOON"
    return "🔵 Pending"


def get_staging():
    s = st.session_state.staging.merge(
        st.session_state.orders[["order_id", "customer"]], on="order_id", how="left")
    s["pickup_flag"] = s.apply(pickup_flag, axis=1)
    return s


def add_exception(ref, etype, desc, prio, owner, action):
    ex = st.session_state.exceptions
    dup = ex[(ex["ref"] == ref) & (ex["type"] == etype) & (ex["status"] != "Resolved")]
    if len(dup) > 0:
        return False
    new_id = f"EX-{len(ex) + 1:03d}"
    row = pd.DataFrame([[new_id, ref, etype, desc, prio, owner, action, "Open"]], columns=ex.columns)
    st.session_state.exceptions = pd.concat([ex, row], ignore_index=True)
    return True


def show(df, color_fn=None):
    df = df.reset_index(drop=True)
    if color_fn is None:
        st.dataframe(df, hide_index=True)
    else:
        def f(r):
            return [color_fn(r)] * len(r)
        st.dataframe(df.style.apply(f, axis=1), hide_index=True)


RED, AMBER, GREEN = "background-color:#fdd9d9", "background-color:#fff1cc", "background-color:#e3f6e5"


def order_table(df):
    t = pd.DataFrame({
        "Order ID": df["order_id"], "Customer": df["customer"],
        "Product": df["product"], "Variant": df["variant"], "Qty": df["qty"],
        "Priority": df["is_priority"].map({True: "⚡ PRIORITY", False: "Regular"}),
        "Ship by": df["deadline"].dt.strftime("%d %b %H:%M"),
        "Status": df["status"], "Assigned to": df["employee"],
        "Location": df["location"], "Alert": df["alert"],
    })

    def color(r):
        if r["Status"] == "Blocked":
            return RED
        if r["Status"] == "Shipped":
            return GREEN
        if "PRIORITY" in r["Priority"]:
            return AMBER
        return ""
    return t, color


# ---------------- PAGES ----------------
def page_dashboard():
    o = get_orders()
    stg = get_staging()
    st.title("📦 Fulfillment Dashboard")
    st.caption("Demo time: 03 Oct 2026, 14:00. Orders ship from the MAIN warehouse only.")

    pri_open = o[o["is_priority"] & (o["status"] != "Shipped")]
    at_risk = pri_open[(pri_open["status"] == "Blocked") | (pri_open["mins_left"] <= 90)]
    if len(at_risk) > 0:
        st.error("🚨 Priority orders needing attention NOW: " + ", ".join(at_risk["order_id"]))
    flagged = stg[stg["pickup_flag"].isin(["🔴 MISSED", "🟠 DUE SOON"])]
    if len(flagged) > 0:
        st.warning("🚚 Courier pickups at risk: " + ", ".join(flagged["order_id"] + " (" + flagged["pickup_flag"] + ")"))

    def cnt(s):
        return int((o["status"] == s).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Total orders today", len(o))
    c2.metric("⚡ Priority orders", int(o["is_priority"].sum()), f"{len(pri_open)} still open", delta_color="off")
    c3.metric("⛔ Blocked / problem orders", cnt("Blocked"))

    c = st.columns(6)
    for col, s in zip(c, STAGES):
        col.metric(s, cnt(s))

    st.subheader("Fulfillment workflow")
    html = ""
    for i, s in enumerate(STAGES):
        cls = "step done" if s == "Shipped" else "step"
        html += f"<span class='{cls}'>{s}<br><span style='font-size:24px'>{cnt(s)}</span></span>"
        if i < len(STAGES) - 1:
            html += "<span class='arrow'>→</span>"
    st.markdown(html, unsafe_allow_html=True)

    st.subheader("⚡ Priority queue (same-day shipping, earliest deadline first)")
    p = pri_open.sort_values("deadline")
    t, _ = order_table(p)
    t = t[["Order ID", "Customer", "Product", "Variant", "Ship by", "Status", "Assigned to", "Alert"]]

    def pcolor(r):
        if r["Status"] == "Blocked" or "PASSED" in r["Alert"]:
            return RED
        if r["Alert"] != "":
            return AMBER
        return ""
    show(t, pcolor)

    st.subheader("⛔ Blocked orders")
    b = o[o["status"] == "Blocked"].sort_values(["is_priority", "deadline"], ascending=[False, True])
    t, color = order_table(b)
    show(t[["Order ID", "Customer", "Product", "Variant", "Priority", "Ship by", "Assigned to", "Alert"]], lambda r: RED)


def page_orders():
    o = get_orders()
    st.title("📋 Orders")
    c1, c2, c3 = st.columns([2, 3, 2])
    q = c1.text_input("Search (order ID, customer, product)")
    status = c2.multiselect("Status", STAGES + ["Blocked"], default=STAGES + ["Blocked"])
    pr = c3.radio("Priority", ["All", "Priority only", "Regular only"], horizontal=True)

    d = o[o["status"].isin(status)]
    if pr == "Priority only":
        d = d[d["is_priority"]]
    elif pr == "Regular only":
        d = d[~d["is_priority"]]
    if q.strip():
        k = q.strip().lower()
        hay = (d["order_id"] + " " + d["customer"] + " " + d["product"] + " " + d["variant"]).str.lower()
        d = d[hay.str.contains(k, regex=False)]
    d = d.sort_values(["is_priority", "deadline"], ascending=[False, True])
    st.caption(f"Showing {len(d)} of {len(o)} orders. 🟨 Priority  🟥 Blocked  🟩 Shipped")
    t, color = order_table(d)
    show(t, color)


def page_inventory():
    inv = get_inventory()
    o = get_orders()
    dem = o[o["stage"].isin(OPEN_STAGES)].groupby("sku")["qty"].sum()
    inv["open_demand"] = inv["sku"].map(dem).fillna(0).astype(int)
    inv["transfer_qty"] = (inv["open_demand"] - inv["avail_main"]).clip(lower=0).astype(int)

    def sstatus(r):
        if r["transfer_qty"] > 0:
            if r["secondary_stock"] >= r["transfer_qty"]:
                return f"🔴 Transfer {r['transfer_qty']} from secondary"
            return "🔴 Out of stock"
        if r["avail_main"] == 0:
            return "🟠 Unavailable in main"
        return "✅ OK"

    inv["stock_status"] = inv.apply(sstatus, axis=1)
    blk = o[o["status"] == "Blocked"].groupby("sku")["order_id"].apply(lambda s: ", ".join(s))
    inv["blocking"] = inv["sku"].map(blk).fillna("")

    st.title("🏷️ Inventory")
    st.info("Rule: orders can ONLY ship from the Main warehouse. Stock in Secondary must be transferred first.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Stock mismatches", int(inv["check"].str.contains("Mismatch").sum()))
    c2.metric("Unavailable in main", int((inv["avail_main"] == 0).sum()))
    c3.metric("Transfers needed", int((inv["transfer_qty"] > 0).sum()))

    t = pd.DataFrame({
        "SKU": inv["sku"], "Product": inv["product"], "Variant": inv["variant"],
        "Main (system)": inv["main_stock"], "Secondary": inv["secondary_stock"],
        "System total": inv["system_total"],
        "Physical count (main)": inv["physical_main"].apply(lambda x: "-" if pd.isna(x) else int(x)),
        "Check": inv["check"], "Stock status": inv["stock_status"],
        "Orders blocked by this SKU": inv["blocking"],
    })

    def color(r):
        if r["Stock status"].startswith("🔴"):
            return RED
        if "Mismatch" in r["Check"] or r["Stock status"].startswith("🟠"):
            return AMBER
        return ""
    show(t, color)

    tr = inv[inv["transfer_qty"] > 0]
    if len(tr) > 0:
        st.subheader("🔁 Transfer list (secondary → main)")
        for _, r in tr.iterrows():
            st.error(f"Move at least {r['transfer_qty']} × {r['product']} – {r['variant']} ({r['sku']}) "
                     f"from the secondary warehouse to MAIN. Secondary has {r['secondary_stock']}.")


def page_pickcheck():
    o = get_orders()
    inv = get_inventory()
    st.title("✅ Pick Check (stop wrong products)")
    st.write("Pick the order, then choose what the picker actually found on the shelf.")
    open_o = o[o["stage"].isin(["Received", "Processing", "Picking", "Packing", "Blocked"])].sort_values("order_id")
    labels = {r["order_id"]: f"{r['order_id']} – {r['product']} {r['variant']} ×{r['qty']} ({r['stage']})"
              for _, r in open_o.iterrows()}
    oid = st.selectbox("Order", list(labels.keys()), format_func=lambda x: labels[x],
                       index=list(labels.keys()).index("XYZ-10515"))
    order = open_o[open_o["order_id"] == oid].iloc[0]
    skus = {r["sku"]: f"{r['product']} – {r['variant']} ({r['sku']})" for _, r in inv.iterrows()}
    found = st.selectbox("What did the picker find?", list(skus.keys()), format_func=lambda x: skus[x])

    if st.button("Verify item", type="primary"):
        st.session_state.pick_result = {"order": oid, "found": found}

    res = st.session_state.get("pick_result")
    if res and res["order"] == oid:
        f = inv[inv["sku"] == res["found"]].iloc[0]
        exp_txt = f"{order['product']} – {order['variant']}"
        fnd_txt = f"{f['product']} – {f['variant']}"
        st.markdown(f"**Expected:** {exp_txt} ({order['sku']})")
        st.markdown(f"**Found:** {fnd_txt} ({f['sku']})")
        if f["sku"] == order["sku"]:
            st.success("**Result:** ✅ Match – OK to continue.")
            if order["stage"] == "Picking" and st.button("Confirm pick → move to Packing"):
                st.session_state.orders.loc[st.session_state.orders["order_id"] == oid, "stage"] = "Packing"
                st.session_state.pop("pick_result", None)
                st.success(f"{oid} moved to Packing.")
        else:
            kind = "Variant mismatch" if f["product"] == order["product"] else "Wrong product"
            st.error(f"**Result:** ⛔ {kind} – STOP and verify. Do not pack this item.")
            if st.button("Log exception and block order"):
                msg = f"Expected {exp_txt}, found {fnd_txt}"
                add_exception(oid, kind + " found", msg, "High", "Ravi (Warehouse)",
                              "Return item to shelf and re-pick the correct SKU")
                m = st.session_state.orders["order_id"] == oid
                st.session_state.orders.loc[m, "stage"] = "Blocked"
                st.session_state.orders.loc[m, "block_reason"] = f"{kind} ({msg})"
                st.session_state.pop("pick_result", None)
                st.success(f"{oid} is now Blocked and an exception was logged (see Exceptions page).")


def page_staging():
    st.title("🚚 Staging & Courier Pickup")
    s = get_staging()
    pending = s[s["pickup_status"] == "Pending"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Waiting for pickup", len(pending))
    c2.metric("🟠 Due within 60 min", int((s["pickup_flag"] == "🟠 DUE SOON").sum()))
    c3.metric("🔴 Missed", int((s["pickup_flag"] == "🔴 MISSED").sum()))
    view = st.radio("Show", ["Waiting for pickup", "All"], horizontal=True)
    d = pending if view == "Waiting for pickup" else s
    d = d.sort_values("pickup_deadline")
    t = pd.DataFrame({
        "Order ID": d["order_id"], "Customer": d["customer"], "Packing status": d["packing_status"],
        "Staging location": d["location"], "Courier": d["courier"],
        "Pickup": d["pickup_status"], "Pickup deadline": d["pickup_deadline"].dt.strftime("%H:%M"),
        "Flag": d["pickup_flag"],
    })

    def color(r):
        if "MISSED" in r["Flag"]:
            return RED
        if "DUE SOON" in r["Flag"]:
            return AMBER
        if "Collected" in r["Flag"]:
            return GREEN
        return ""
    show(t, color)

    st.subheader("Actions")
    a1, a2 = st.columns(2)
    with a1:
        if len(pending) > 0:
            pick = st.selectbox("Courier collected this order:", list(pending["order_id"]))
            if st.button("Mark collected / shipped"):
                st.session_state.staging.loc[st.session_state.staging["order_id"] == pick, "pickup_status"] = "Collected"
                st.session_state.orders.loc[st.session_state.orders["order_id"] == pick, "stage"] = "Shipped"
                st.session_state.orders.loc[st.session_state.orders["order_id"] == pick, "location"] = "Dispatched"
                st.success(f"{pick} marked as Shipped.")
        else:
            st.write("No orders waiting for pickup.")
    with a2:
        st.write("Turn late or nearly-late pickups into tracked exceptions:")
        if st.button("Log pickup exceptions"):
            n = 0
            for _, r in s[s["pickup_flag"].isin(["🔴 MISSED", "🟠 DUE SOON"])].iterrows():
                word = "missed" if "MISSED" in r["pickup_flag"] else "due soon"
                ok = add_exception(r["order_id"], "Courier pickup delay",
                                   f"{r['courier']} pickup {word} (deadline {r['pickup_deadline']:%H:%M}), box at {r['location']}",
                                   "High", "Anita (Office)", f"Call {r['courier']} to confirm collection")
                n += int(ok)
            st.success(f"{n} new exception(s) logged." if n else "All flagged pickups are already in the exception log.")


def page_exceptions():
    st.title("⚠️ Exceptions")
    st.caption("Rule: every problem must have an owner and a next action.")
    ex = st.session_state.exceptions
    c1, c2, c3 = st.columns(3)
    c1.metric("Open / in progress", int((ex["status"] != "Resolved").sum()))
    c2.metric("High priority open", int(((ex["priority"] == "High") & (ex["status"] != "Resolved")).sum()))
    c3.metric("Missing owner or action", int(((ex["owner"].str.strip() == "") | (ex["next_action"].str.strip() == "")).sum()))

    f1, f2 = st.columns(2)
    sf = f1.multiselect("Status", ["Open", "In Progress", "Resolved"], default=["Open", "In Progress"])
    pf = f2.multiselect("Priority", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
    d = ex[ex["status"].isin(sf) & ex["priority"].isin(pf)]
    t = d.rename(columns={"exception_id": "Exception ID", "ref": "Order / SKU", "type": "Type",
                          "description": "Problem", "priority": "Priority", "owner": "Owner",
                          "next_action": "Next action", "status": "Status"})

    def color(r):
        if r["Status"] == "Resolved":
            return GREEN
        return RED if r["Priority"] == "High" else AMBER
    show(t, color)

    st.subheader("Update an exception")
    eid = st.selectbox("Exception", list(ex["exception_id"]))
    cur = ex[ex["exception_id"] == eid].iloc[0]
    statuses = ["Open", "In Progress", "Resolved"]
    ns = st.selectbox("Status", statuses, index=statuses.index(cur["status"]), key=f"s_{eid}")
    no = st.text_input("Owner", value=cur["owner"], key=f"o_{eid}")
    na = st.text_input("Next action", value=cur["next_action"], key=f"a_{eid}")
    if st.button("Save changes"):
        if no.strip() == "" or na.strip() == "":
            st.error("Owner and next action are required.")
        else:
            m = st.session_state.exceptions["exception_id"] == eid
            st.session_state.exceptions.loc[m, ["status", "owner", "next_action"]] = [ns, no.strip(), na.strip()]
            st.success(f"{eid} updated.")


PAGES = {
    "Dashboard": page_dashboard, "Orders": page_orders, "Inventory": page_inventory,
    "Exceptions": page_exceptions, "Pick Check": page_pickcheck,
    "Staging": page_staging,
}
st.sidebar.title("📦 XYZ Fulfillment Hub")
choice = st.sidebar.radio("Go to", list(PAGES.keys()))
PAGES[choice]()
