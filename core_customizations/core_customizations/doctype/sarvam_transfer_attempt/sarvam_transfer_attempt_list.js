// [BR-TEL-006] Colour each transfer decision by its status.
frappe.listview_settings["Sarvam Transfer Attempt"] = {
	get_indicator(doc) {
		const colours = {
			Routed: "orange",
			Connected: "blue",
			"Not connected": "gray",
			Ended: "green",
			Expired: "gray",
			Refused: "red",
		};
		return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
	},
};
