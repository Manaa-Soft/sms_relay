frappe.provide("sms_relay");

frappe.ui.form.on("SMS Bulk Message", {
    refresh(frm) {
        if (frm.doc.status === "Processing") {
            frm.dashboard.add_comment("Bulk message is being processed...", "blue", true);
        }
        if (frm.doc.status === "Completed") {
            frm.dashboard.add_comment(
                `Completed: ${frm.doc.sent_count} sent, ${frm.doc.failed_count} failed`,
                frm.doc.failed_count > 0 ? "orange" : "green",
                true
            );
        }
        if (!frm.is_new() && frm.doc.status === "Draft") {
            frm.add_custom_button("Start Sending", () => {
                frappe.confirm("Start sending this bulk message?", () => {
                    frappe.call({
                        method: "sms_relay.core.bulk_engine.process_bulk_job",
                        args: { bulk_name: frm.doc.name },
                        freeze: true,
                        freeze_message: "Starting bulk send...",
                        callback: () => frm.reload_doc()
                    });
                });
            }, "Actions").addClass("btn-primary-dark");
        }
        if (!frm.is_new() && frm.doc.status !== "Completed" && frm.doc.status !== "Cancelled") {
            frm.add_custom_button("Cancel", () => {
                frappe.confirm("Cancel this bulk message?", () => {
                    frappe.call({
                        method: "sms_relay.core.bulk_engine.cancel_bulk_job",
                        args: { bulk_name: frm.doc.name },
                        callback: () => frm.reload_doc()
                    });
                });
            }, "Actions").addClass("btn-danger");
        }
        if (!frm.is_new() && frm.doc.recipients && frm.doc.recipients.length > 0) {
            _render_bulk_progress(frm);
        }
    },

    message_type(frm) {
        frm.toggle_display("message", frm.doc.message_type === "Text");
        frm.toggle_display("template", frm.doc.message_type === "Template");
    },

    message(frm) {
        if (frm.doc.message) {
            _update_char_count(frm, frm.doc.message);
        }
    },

    recipients_csv(frm) {
        if (frm.doc.recipients_csv) {
            _parse_csv(frm, frm.doc.recipients_csv);
        }
    }
});

function _render_bulk_progress(frm) {
    const total = frm.doc.total_recipients || 0;
    const sent = frm.doc.sent_count || 0;
    const failed = frm.doc.failed_count || 0;
    const pending = frm.doc.pending_count || 0;
    if (total === 0) return;
    const pct = Math.round(((sent + failed) / total) * 100);
    const html = `<div style="margin:10px 0;padding:10px;background:#f8f9fa;border-radius:4px;">
        <div class="progress" style="height:20px;margin-bottom:8px;">
            <div class="progress-bar bg-success" style="width:${Math.round((sent/total)*100)}%">${sent} Sent</div>
            <div class="progress-bar bg-danger" style="width:${Math.round((failed/total)*100)}%">${failed} Failed</div>
        </div>
        <small class="text-muted">${sent} sent, ${failed} failed, ${pending} pending (${total} total)</small>
    </div>`;
    frm.dashboard.add_comment("");
    frm.$wrapper.find(".sms-bulk-progress").remove();
    frm.$wrapper.find(".form-page").first().prepend(`<div class="sms-bulk-progress">${html}</div>`);
}

function _update_char_count(frm, text) {
    const is_gsm7 = /^[\@\£\$\¥\è\é\ù\ì\ò\ç\n\Ø\ø\r\Å\å\Δ\_\Φ\Γ\Λ\Ω\Π\Ψ\Σ\Θ\Ξ\x1bÆæßÉ\s!\"#¤%&'\(\)\*\+,\-\.\/0-9:;<=>?¡A-ZÄÖÑÜ¿a-zäöñüà]+$/.test(text);
    const len = text.length;
    let max_chars, parts;
    if (is_gsm7) {
        max_chars = 160;
        parts = len <= 160 ? 1 : Math.ceil(len / 153);
    } else {
        max_chars = 70;
        parts = len <= 70 ? 1 : Math.ceil(len / 67);
    }
    const color = len > max_chars ? "#dc3545" : "#28a745";
    frm.dashboard.set_headline(`<span style="color:${color}">Characters: ${len} | Encoding: ${is_gsm7 ? "GSM-7" : "Unicode"} | SMS Parts: ${parts}</span>`);
}

function _parse_csv(frm, csv_text) {
    try {
        const lines = csv_text.trim().split("\n");
        if (lines.length < 2) {
            frappe.msgprint("CSV must have a header row and at least one data row");
            return;
        }
        const headers = lines[0].split(",").map(h => h.trim().toLowerCase());
        const phoneIdx = headers.findIndex(h => ["phone", "mobile", "number", "phone_number", "mobile_number"].includes(h));
        const nameIdx = headers.findIndex(h => ["name", "recipient_name", "customer_name"].includes(h));
        if (phoneIdx === -1) {
            frappe.msgprint("CSV must have a 'phone', 'mobile', or 'number' column");
            return;
        }
        const recipients = [];
        for (let i = 1; i < lines.length; i++) {
            const cols = lines[i].split(",").map(c => c.trim());
            if (cols[phoneIdx]) {
                recipients.push({
                    phone: cols[phoneIdx],
                    recipient_name: nameIdx >= 0 ? cols[nameIdx] : "",
                    status: "Pending"
                });
            }
        }
        frm.clear_table("recipients");
        recipients.forEach(r => {
            const row = frm.add_child("recipients");
            row.phone = r.phone;
            row.recipient_name = r.recipient_name;
            row.status = r.status;
        });
        frm.refresh_field("recipients");
        frm.doc.total_recipients = recipients.length;
        frm.doc.pending_count = recipients.length;
        frappe.show_alert(`${recipients.length} recipients loaded from CSV`);
    } catch(e) {
        frappe.msgprint("Error parsing CSV: " + e.message);
    }
}
