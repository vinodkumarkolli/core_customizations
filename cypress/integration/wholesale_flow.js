context("Wholesale Flow (SO -> DN -> SI)", () => {
	let so_name;
	let dn_name;

	before(() => {
		cy.login();
		// Create a fresh Submitted Sales Order
		cy.window().its("frappe").then((frappe) => {
			return frappe.xcall("core_customizations.tests.test_ui_wholesale_helpers.setup_cypress_wholesale_data").then((name) => {
				so_name = name;
			});
		});
	});

	after(() => {
		if (so_name) {
			cy.window().its("frappe").then((frappe) => {
				return frappe.xcall("core_customizations.tests.test_ui_wholesale_helpers.cleanup_cypress_wholesale_data", { so_name: so_name });
			});
		}
	});

	it("creates a Delivery Note from Sales Order", () => {
		cy.visit(`/app/sales-order/${so_name}`);
		cy.get(".page-title").should("contain", so_name);

		// Click Create -> Delivery Note
		cy.get(".page-actions button").contains("Create").click();
		cy.get(".dropdown-menu a").contains("Delivery Note").click();

		// Wait for DN to open
		cy.get(".page-title").should("contain", "New Delivery Note");
		
		// Set warehouse to satisfy the single warehouse validation
		cy.get("div[data-fieldname='set_warehouse'] input").clear().type("Stores - SE-K{enter}");
		
		// Wait for frappe to update rows
		cy.wait(500);

		// Save and Submit
		cy.get(".page-actions button.primary-action").contains("Save").click();
		cy.wait(1000);
		cy.get(".page-actions button.primary-action").contains("Submit").click();
		
		// Confirm Submission
		cy.get(".modal-dialog .btn-primary").contains("Yes").click();
		cy.wait(1000);

		cy.get(".page-title").should("not.contain", "New Delivery Note");
		
		// Capture DN name for next test
		cy.get(".page-title .title-text").then(($el) => {
			dn_name = $el.text().trim();
		});
	});

	it("creates a Sales Invoice from Delivery Note with update_stock=0", () => {
		cy.visit(`/app/delivery-note/${dn_name}`);
		cy.get(".page-title").should("contain", dn_name);

		// Click Create -> Sales Invoice
		cy.get(".page-actions button").contains("Create").click();
		cy.get(".dropdown-menu a").contains("Sales Invoice").click();

		// Wait for SI to open
		cy.get(".page-title").should("contain", "New Sales Invoice");

		// Assert update_stock is unchecked
		cy.get("input[data-fieldname='update_stock']").should("not.be.checked");

		// Save and Submit
		cy.get(".page-actions button.primary-action").contains("Save").click();
		cy.wait(1000);
		cy.get(".page-actions button.primary-action").contains("Submit").click();
		
		// Confirm Submission
		cy.get(".modal-dialog .btn-primary").contains("Yes").click();
		cy.wait(1000);

		cy.get(".page-title").should("not.contain", "New Sales Invoice");
	});
});
