// Copyright (c) 2026, Vinod Kumar K and contributors
// For license information, please see license.txt

/**
 * @functionalPurpose Transfers menu on Sarvam Voice Agent Settings: who is
 * busy right now and since when, a button that frees every executive the
 * busy ledger holds, and the log of every routing decision.
 * @businessPurpose [BR-TEL-006] Lets a manager see and fix the live-transfer
 * busy state without opening the Transfer Attempt rows one by one.
 */
frappe.ui.form.on("Sarvam Voice Agent Settings", {
	refresh(frm) {
		const group = __("Transfers");
		frm.add_custom_button(__("Who Is Busy"), () => show_busy_executives(), group);
		frm.add_custom_button(
			__("Clear Busy Flags"),
			() =>
				frappe.confirm(
					__("Free every executive the busy ledger holds now? On Break ticks are left as they are."),
					() =>
						frappe
							.call({
								method: "core_customizations.core_customizations.voice_agent.clear_busy_executives",
								freeze: true,
							})
							.then((r) =>
								frappe.show_alert({
									message: __("{0} transfer(s) cleared", [r.message.cleared]),
									indicator: "green",
								})
							)
				),
			group
		);
		frm.add_custom_button(__("Transfer Log"), () => frappe.set_route("List", "Sarvam Transfer Attempt"), group);
	},
});

function show_busy_executives() {
	frappe
		.call("core_customizations.core_customizations.voice_agent.busy_executives")
		.then((r) => {
			const esc = frappe.utils.escape_html;
			const when = (v) => (v ? esc(frappe.datetime.str_to_user(v)) : "");
			const rows = (r.message || [])
				.map((e) => {
					const state = e.on_break ? __("On break") : e.busy ? __(e.status) : __("Free");
					return `<tr>
						<td>${esc(e.executive)}</td><td>${esc(state)}</td><td>${when(e.since)}</td>
						<td>${when(e.free_at)}</td><td>${esc(e.caller_phone || "")}</td>
						<td>${e.attempt ? `<a href="/app/sarvam-transfer-attempt/${encodeURIComponent(e.attempt)}">${esc(e.attempt)}</a>` : ""}</td>
					</tr>`;
				})
				.join("");
			const dialog = new frappe.ui.Dialog({
				title: __("Who Is Busy"),
				size: "large",
				fields: [{ fieldtype: "HTML", fieldname: "table" }],
			});
			dialog.fields_dict.table.$wrapper.html(
				rows
					? `<table class="table table-bordered">
						<thead><tr><th>${__("Executive")}</th><th>${__("State")}</th><th>${__("Since")}</th>
						<th>${__("Free At")}</th><th>${__("Caller")}</th><th>${__("Attempt")}</th></tr></thead>
						<tbody>${rows}</tbody></table>`
					: `<p class="text-muted">${__("No enabled executive with a number.")}</p>`
			);
			dialog.show();
		});
}
