import io
import os
import base64
from datetime import date
import openai
import streamlit as st
from streamlit_paste_button import paste_image_button
from journal import SYSTEM_PROMPT, MODEL, MAX_TOKENS
from entities import (
    list_entities, load_entity, save_entity, delete_entity, entity_context_block,
    load_app_context, save_app_context, app_context_block,
)
from fx import detect_foreign_currency, get_spot_rate, fx_context_line
from excel_processor import (
    BATCH_PROMPT_ADDENDUM, extract_images_from_xlsx,
    build_batch_user_message, parse_batch_response, create_output_excel,
)

st.set_page_config(page_title="Journal Entry Generator", page_icon="📒", layout="centered")

api_key = os.environ.get("OPENROUTER_API_KEY")
if not api_key:
    st.error("OPENROUTER_API_KEY is not set.")
    st.stop()


client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=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)

MIME_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

# --- Sidebar ---
with st.sidebar:
    st.header("🏢 Entity")
    entities = list_entities()
    options = ["None (no entity)"] + entities
    selected = st.selectbox("Active entity", options)
    active_entity = None if selected == "None (no entity)" else selected

    if active_entity:
        e = load_entity(active_entity)
        func_currency = e.get("functional_currency", "").upper() or None
        st.caption(e.get("business_context", "")[:200] or "No business context saved.")
        if func_currency:
            st.caption(f"Functional currency: **{func_currency}**")
    else:
        func_currency = None

    st.divider()
    st.success("FX rates: enabled (Frankfurter/ECB)", icon="💱")


def build_system_prompt() -> str:
    prompt = SYSTEM_PROMPT
    app_ctx = app_context_block()
    if app_ctx:
        prompt += "\n\n" + app_ctx
    if active_entity:
        prompt += "\n\n" + entity_context_block(active_entity)
    return prompt


def resolve_fx(text: str, txn_date: date) -> str | None:
    """Return an FX context line to prepend to the user message, or None."""
    if not func_currency:
        return None
    foreign = detect_foreign_currency(text, func_currency)
    if not foreign:
        return None
    rate = get_spot_rate(foreign, func_currency, txn_date)
    if not rate:
        st.warning(f"Could not fetch {foreign}/{func_currency} rate for {txn_date}. Proceeding without translation.")
        return None
    st.info(f"💱 {foreign} → {func_currency}: 1 {foreign} = {rate:.4f} {func_currency} ({txn_date.strftime('%d %b %Y')})")
    return fx_context_line(foreign, func_currency, rate, txn_date)


def stream_journal_entry(messages, tab_key):
    output = st.empty()
    full_text = ""
    usage = None
    stream = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            full_text += chunk.choices[0].delta.content
            output.markdown(f"```\n{full_text}\n```")
        if getattr(chunk, "usage", None):
            usage = chunk.usage
    if usage:
        st.caption(f"Tokens — input: {usage.prompt_tokens}  ·  output: {usage.completion_tokens}")
    st.session_state[f"{tab_key}_messages"] = messages + [{"role": "assistant", "content": full_text}]


def render_refinement(tab_key):
    if f"{tab_key}_messages" not in st.session_state:
        return
    st.divider()
    refinement = st.text_area(
        "Something wrong or missing? Describe what to correct:",
        placeholder="e.g. This was paid on credit, not cash / The VAT should be split out separately",
        height=80,
        key=f"{tab_key}_refinement",
    )
    if st.button("Refine", type="secondary", use_container_width=True, key=f"{tab_key}_btn_refine"):
        if not refinement.strip():
            st.warning("Please describe what needs to be corrected.")
        else:
            updated = st.session_state[f"{tab_key}_messages"] + [{"role": "user", "content": refinement.strip()}]
            try:
                stream_journal_entry(updated, tab_key)
            except openai.APIError as e:
                st.error(f"API error: {e}")


def handle_errors(fn):
    try:
        fn()
    except openai.AuthenticationError:
        st.error("Invalid API key. Check OPENROUTER_API_KEY.")
    except openai.RateLimitError:
        st.warning("Rate limited. Please wait a moment and try again.")
    except openai.APIConnectionError:
        st.error("Could not reach OpenRouter. Check your network.")
    except openai.APIStatusError as e:
        st.error(f"API error {e.status_code}: {e.message}")


# --- Tabs ---
st.title("📒 Journal Entry Generator")
tab_text, tab_image, tab_excel, tab_entities, tab_app = st.tabs(
    ["✏️ Text Description", "🧾 Invoice Image", "📊 Excel Batch", "🏢 Entities", "⚙️ App Context"]
)

with tab_text:
    transaction = st.text_area(
        "Transaction description",
        placeholder="e.g. Paid €500 rent for office space",
        height=80,
    )
    txn_date = st.date_input("Transaction date", value=date.today(), key="txn_date_text")
    if st.button("Generate", type="primary", use_container_width=True, key="btn_text"):
        if not transaction.strip():
            st.warning("Please enter a transaction description.")
        else:
            st.session_state.pop("text_messages", None)
            fx_line = resolve_fx(transaction, txn_date)
            user_content = f"{fx_line}\n{transaction.strip()}" if fx_line else transaction.strip()
            handle_errors(lambda: stream_journal_entry([
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": user_content},
            ], "text"))
    render_refinement("text")

with tab_image:
    uploaded = st.file_uploader("Upload an invoice", type=["jpg", "jpeg", "png", "webp"])
    paste_result = paste_image_button("📋 Paste from clipboard", key="clipboard")

    if uploaded:
        buf = io.BytesIO()
        uploaded.seek(0)
        buf.write(uploaded.read())
        st.session_state["invoice_image"] = buf.getvalue()
        st.session_state["invoice_mime"] = MIME_TYPES.get(uploaded.name.rsplit(".", 1)[-1].lower(), "image/jpeg")
    if paste_result.image_data is not None:
        buf = io.BytesIO()
        paste_result.image_data.save(buf, format="PNG")
        st.session_state["invoice_image"] = buf.getvalue()
        st.session_state["invoice_mime"] = "image/png"

    if "invoice_image" in st.session_state:
        st.image(st.session_state["invoice_image"], use_container_width=True)

    col_currency, col_date = st.columns(2)
    with col_currency:
        invoice_currency = st.text_input(
            "Invoice currency (optional)",
            placeholder="e.g. EUR",
            help="If the invoice currency differs from your functional currency, enter the ISO code here.",
            key="invoice_currency",
        ).strip().upper()
    with col_date:
        txn_date_img = st.date_input("Transaction date", value=date.today(), key="txn_date_image")

    if st.button("Generate from Invoice", type="primary", use_container_width=True, key="btn_image"):
        if "invoice_image" not in st.session_state:
            st.warning("Please upload or paste an invoice image first.")
        else:
            b64 = base64.b64encode(st.session_state["invoice_image"]).decode("utf-8")
            mime = st.session_state["invoice_mime"]
            st.session_state.pop("image_messages", None)

            fx_line = None
            if invoice_currency and func_currency and invoice_currency != func_currency:
                rate = get_spot_rate(invoice_currency, func_currency, txn_date_img)
                if rate:
                    st.info(f"💱 {invoice_currency} → {func_currency}: 1 {invoice_currency} = {rate:.4f} {func_currency} ({txn_date_img.strftime('%d %b %Y')})")
                    fx_line = fx_context_line(invoice_currency, func_currency, rate, txn_date_img)
                else:
                    st.warning(f"Could not fetch {invoice_currency}/{func_currency} rate. Proceeding without translation.")

            img_text = "Generate the journal entry for this invoice."
            if fx_line:
                img_text = f"{fx_line}\n{img_text}"

            handle_errors(lambda: stream_journal_entry([
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": img_text},
                    ],
                },
            ], "image"))
    render_refinement("image")

with tab_excel:
    st.subheader("Batch Processing from Excel")
    st.caption(
        "Upload an Excel workbook where each sheet represents one transaction. "
        "Each sheet may contain one or more invoice images. "
        "All images on a sheet are consolidated into one journal entry."
    )

    excel_upload = st.file_uploader("Upload Excel workbook (.xlsx)", type=["xlsx"], key="excel_upload")

    if excel_upload:
        xlsx_bytes = excel_upload.read()
        upload_key = f"{excel_upload.name}_{len(xlsx_bytes)}"

        if st.session_state.get("excel_upload_key") != upload_key:
            st.session_state["excel_upload_key"] = upload_key
            st.session_state.pop("excel_results", None)
            st.session_state.pop("excel_output", None)
            try:
                st.session_state["excel_images_by_sheet"] = extract_images_from_xlsx(xlsx_bytes)
            except Exception as exc:
                st.error(f"Could not read workbook: {exc}")
                st.session_state["excel_images_by_sheet"] = {}

        images_by_sheet = st.session_state.get("excel_images_by_sheet", {})

        col_fc, col_date = st.columns(2)
        with col_fc:
            batch_fc = st.text_input(
                "Functional currency",
                value=func_currency or "GBP",
                placeholder="e.g. GBP",
                key="batch_fc",
            ).strip().upper() or "GBP"
        with col_date:
            txn_date_batch = st.date_input("Transaction date (for FX rates)", value=date.today(), key="txn_date_batch")

        if images_by_sheet:
            preview_rows = [
                {"Sheet (Transaction)": name, "Images Found": len(imgs)}
                for name, imgs in images_by_sheet.items()
            ]
            st.dataframe(preview_rows, use_container_width=True, hide_index=True)
            total_imgs = sum(len(v) for v in images_by_sheet.values())
            sheets_with_imgs = sum(1 for v in images_by_sheet.values() if v)
            st.caption(f"{sheets_with_imgs} sheet(s) with images · {total_imgs} total image(s)")
        else:
            st.info("No images detected in any sheet.")

        if st.button("⚙️ Process All Transactions", type="primary", use_container_width=True, key="btn_excel"):
            if not images_by_sheet:
                st.warning("No images found to process.")
            else:
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                sheets = list(images_by_sheet.items())

                for idx, (sheet_name, images) in enumerate(sheets):
                    status_text.text(f"Processing '{sheet_name}' ({idx + 1} / {len(sheets)})…")
                    if not images:
                        results.append({
                            "transaction_number": sheet_name,
                            "doc_numbers": "N/A",
                            "native_amount": "",
                            "functional_amount": "",
                            "journal_entry": "",
                            "error": "No images found in this sheet.",
                        })
                    else:
                        try:
                            content = build_batch_user_message(images, sheet_name)
                            system = build_system_prompt() + "\n\n" + BATCH_PROMPT_ADDENDUM
                            resp = client.chat.completions.create(
                                model=MODEL,
                                max_tokens=MAX_TOKENS,
                                messages=[
                                    {"role": "system", "content": system},
                                    {"role": "user", "content": content},
                                ],
                            )
                            raw = resp.choices[0].message.content or ""
                            doc_nums, txn_currency, txn_amount_str, journal = parse_batch_response(raw)

                            # Format native amount
                            native_amount = f"{txn_currency} {txn_amount_str}" if txn_currency and txn_currency != "N/A" and txn_amount_str and txn_amount_str != "N/A" else "N/A"

                            # Compute functional currency amount via FX
                            functional_amount = native_amount
                            if txn_currency and txn_currency not in ("N/A", "") and txn_amount_str and txn_amount_str not in ("N/A", ""):
                                try:
                                    amount_val = float(txn_amount_str.replace(",", ""))
                                    if txn_currency.upper() == batch_fc.upper():
                                        functional_amount = f"{batch_fc} {amount_val:,.2f}"
                                    else:
                                        rate = get_spot_rate(txn_currency, batch_fc, txn_date_batch)
                                        if rate:
                                            functional_amount = f"{batch_fc} {amount_val * rate:,.2f}"
                                        else:
                                            functional_amount = "Rate unavailable"
                                except ValueError:
                                    functional_amount = "Parse error"

                            results.append({
                                "transaction_number": sheet_name,
                                "doc_numbers": doc_nums,
                                "native_amount": native_amount,
                                "functional_amount": functional_amount,
                                "journal_entry": journal,
                            })
                        except openai.APIError as exc:
                            results.append({
                                "transaction_number": sheet_name,
                                "doc_numbers": "N/A",
                                "native_amount": "",
                                "functional_amount": "",
                                "journal_entry": "",
                                "error": f"API error: {exc}",
                            })
                    progress_bar.progress((idx + 1) / len(sheets))

                status_text.empty()
                progress_bar.empty()
                st.session_state["excel_results"] = results
                st.session_state["excel_output"] = create_output_excel(results)

        if "excel_results" in st.session_state:
            results = st.session_state["excel_results"]
            st.subheader("Results Preview")
            st.dataframe(
                [
                    {
                        "Transaction": r["transaction_number"],
                        "Documents": r["doc_numbers"],
                        "Native Amount": r.get("native_amount", ""),
                        "Functional Amount": r.get("functional_amount", ""),
                        "Journal Posting": (r.get("journal_entry") or r.get("error", ""))[:120],
                    }
                    for r in results
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "📥 Download Journal Entries (.xlsx)",
                data=st.session_state["excel_output"],
                file_name="journal_entries.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
                key="download_excel",
            )

with tab_entities:
    st.subheader("Entity Profiles")
    st.caption("Profiles are saved to disk and automatically used as context when the entity is selected in the sidebar.")

    all_entities = list_entities()
    mode = st.radio("", ["Create new entity", "Edit existing entity"], horizontal=True, label_visibility="collapsed")

    if mode == "Edit existing entity":
        if not all_entities:
            st.info("No entities saved yet. Switch to 'Create new entity' to add one.")
            st.stop()
        chosen = st.selectbox("Select entity to edit", all_entities)
        prefill = load_entity(chosen)
    else:
        chosen = None
        prefill = {"name": "", "functional_currency": "", "business_context": "", "accounting_policies": "", "accounting_standards": ""}

    with st.form("entity_form"):
        name = st.text_input("Entity name *", value=prefill["name"], disabled=(mode == "Edit existing entity"))
        functional_currency = st.text_input(
            "Functional currency (ISO code)",
            value=prefill.get("functional_currency", ""),
            placeholder="e.g. USD, GBP, AUD",
            help="Used for automatic FX translation when a transaction is in a different currency.",
        )
        business_context = st.text_area(
            "Business context",
            value=prefill.get("business_context", ""),
            height=120,
            placeholder="Describe the nature of the business, industry, size, operations, etc.",
        )
        accounting_policies = st.text_area(
            "Accounting policy choices",
            value=prefill.get("accounting_policies", ""),
            height=120,
            placeholder="e.g. Revenue recognised on cash receipt. Inventory valued using FIFO. Straight-line depreciation over useful life.",
        )
        accounting_standards = st.text_area(
            "Accounting standards",
            value=prefill.get("accounting_standards", ""),
            height=100,
            placeholder="e.g. Financial statements prepared under IFRS as adopted by the IASB.",
        )

        col_save, col_delete = st.columns([3, 1])
        with col_save:
            submitted = st.form_submit_button("💾 Save", type="primary", use_container_width=True)
        with col_delete:
            delete_clicked = st.form_submit_button("🗑️ Delete", use_container_width=True, disabled=(mode == "Create new entity"))

    if submitted:
        label = name.strip() if mode == "Create new entity" else chosen
        if not label:
            st.error("Entity name is required.")
        else:
            save_entity({
                "name": label,
                "functional_currency": functional_currency.strip().upper(),
                "business_context": business_context.strip(),
                "accounting_policies": accounting_policies.strip(),
                "accounting_standards": accounting_standards.strip(),
            })
            st.success(f"Saved **{label}**.")
            st.rerun()

    if delete_clicked and chosen:
        delete_entity(chosen)
        st.success(f"Deleted **{chosen}**.")
        st.rerun()

with tab_app:
    st.subheader("Application Context")
    st.caption("This context applies globally to every journal entry generation, regardless of which entity is selected. Entity-specific context is layered on top.")

    app_ctx = load_app_context()

    with st.form("app_context_form"):
        general_context = st.text_area(
            "General context",
            value=app_ctx.get("general_context", ""),
            height=120,
            placeholder="e.g. This application is used by a mid-size accounting firm in Australia. All amounts are in AUD.",
        )
        default_policies = st.text_area(
            "Default accounting policies",
            value=app_ctx.get("default_policies", ""),
            height=120,
            placeholder="e.g. Unless overridden by the entity, use accrual basis accounting and the perpetual inventory method.",
        )
        default_standards = st.text_area(
            "Default accounting standards",
            value=app_ctx.get("default_standards", ""),
            height=100,
            placeholder="e.g. Unless stated otherwise, financial statements are prepared under IFRS.",
        )
        if st.form_submit_button("💾 Save", type="primary", use_container_width=True):
            save_app_context({
                "general_context": general_context.strip(),
                "default_policies": default_policies.strip(),
                "default_standards": default_standards.strip(),
            })
            st.success("Application context saved.")
