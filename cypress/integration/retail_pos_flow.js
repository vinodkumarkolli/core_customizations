context("Retail POS Flow (POS -> SI)", () => {
	let pos_data;
	let pos_invoice_name;

	before(() => {
		cy.login();
		// Create POS Profile and Opening Entry
		cy.window().its("frappe").then((frappe) => {
			return frappe.xcall("core_customizations.tests.test_ui_retail_helpers.setup_cypress_retail_data").then((data) => {
				pos_data = data;
			});
		});
	});

	it("creates a POS Invoice", () => {
		// Instead of navigating the complex POS Vue UI, we will create a POS invoice via standard form 
		// to test the transition from POS Invoice -> Closing Entry -> SI
		cy.visit("/app/pos-invoice/new");
		
		cy.get(".page-title").should("contain", "New POS Invoice");
		
		// Fill details
		cy.get("div[data-fieldname='customer'] input").clear().type(`${pos_data.customer}{enter}`);
		cy.wait(500);

		// Add item
		cy.get("div[data-fieldname='items'] .grid-add-row").click();
		cy.get("div[data-fieldname='item_code'] input").clear().type(`${pos_data.item_code}{enter}`);
		cy.get("input[data-fieldname='qty']").clear().type("2");
		cy.get("input[data-fieldname='rate']").clear().type("100{enter}");

		// Wait for amounts to calculate
		cy.wait(500);

		// Fill Payment
		cy.get("div[data-fieldname='payments'] .grid-add-row").click();
		cy.get("div[data-fieldname='mode_of_payment'] input").last().clear().type("Cash{enter}");
		cy.get("input[data-fieldname='amount']").last().clear().type("200{enter}");

		cy.wait(500);
		
		// Save and Submit
		cy.get(".page-actions button.primary-action").contains("Save").click();
		cy.wait(1000);
		cy.get(".page-actions button.primary-action").contains("Submit").click();
		
		// Confirm Submission
		cy.get(".modal-dialog .btn-primary").contains("Yes").click();
		cy.wait(1000);

		cy.get(".page-title .title-text").then(($el) => {
			pos_invoice_name = $el.text().trim();
		});
	});

	it("creates a POS Closing Entry which generates a Consolidated Sales Invoice", () => {
		cy.visit("/app/pos-closing-entry/new");
		
		cy.get(".page-title").should("contain", "New POS Closing Entry");
		
		cy.get("div[data-fieldname='pos_profile'] input").clear().type(`${pos_data.pos_profile}{enter}`);
		cy.wait(500);

		// Click "Get POS Invoices" button to pull in our invoice
		cy.get("button[data-fieldname='get_pos_invoices']").click();
		cy.wait(1000);

		// Assert that the POS invoice is fetched
		cy.get("div[data-fieldname='pos_transactions']").should("contain", pos_invoice_name);

		// Fill expected cash amount to balance it out
		cy.get("div[data-fieldname='payment_reconciliation'] .grid-row").first().within(() => {
			cy.get("input[data-fieldname='expected_amount']").invoke('val').then((val) => {
				cy.get("input[data-fieldname='closing_amount']").clear().type(`${val}{enter}`);
			});
		});

		// Save and Submit Closing Entry
		cy.get(".page-actions button.primary-action").contains("Save").click();
		cy.wait(1000);
		cy.get(".page-actions button.primary-action").contains("Submit").click();
		
		// Confirm Submission
		cy.get(".modal-dialog .btn-primary").contains("Yes").click();
		cy.wait(2000); // Give frappe time to run background consolidation

		// Now assert a Consolidated Sales Invoice was created
		// We can check the dashboard or run a cy.call to check
		cy.window().its("frappe").then((frappe) => {
			return frappe.db.get_list("Sales Invoice", {
				filters: { is_consolidated: 1, is_pos: 1 },
				limit: 1,
				fields: ["name", "update_stock"]
			}).then((invoices) => {
				expect(invoices.length).to.be.greaterThan(0);
				// Most critical check: Consolidated SI must update stock!
				expect(invoices[0].update_stock).to.equal(1);
			});
		});
	});
});
