context("Delivery Note Packing Slips", () => {
	let dn_name;

	before(() => {
		cy.login();
		// Create a fresh Delivery Note using our python helper
		cy.window().its("frappe").then((frappe) => {
			return frappe.xcall("core_customizations.tests.test_ui_helpers.setup_cypress_test_delivery_note").then((name) => {
				dn_name = name;
			});
		});
	});

	after(() => {
		// Clean up the created Delivery Note
		if (dn_name) {
			cy.window().its("frappe").then((frappe) => {
				return frappe.xcall("core_customizations.tests.test_ui_helpers.cleanup_cypress_test_data", { dn_name: dn_name });
			});
		}
	});

	it("renders Manage / Edit Modal correctly and respects Draft restrictions", () => {
		// 1. Visit the Delivery Note
		cy.visit(`/app/delivery-note/${dn_name}`);
		cy.get(".page-title").should("contain", dn_name);

		// 2. Click "Generate" to create a couple of Draft Packing Slips
		cy.get(".page-actions button").contains("Packing Slips").click();
		cy.get(".dropdown-menu a").contains("Generate").click();

		// Wait for generator modal
		cy.get(".modal-dialog").should("contain", "Generate Packing Slips");
		
		// Fill generator fields (Item should default to Cypress Test Item 1)
		cy.get(".modal-dialog input[data-fieldname='qty_per_box']").clear().type("50");
		cy.get(".modal-dialog input[data-fieldname='no_of_boxes']").clear().type("2");
		
		// Click Generate button
		cy.get(".modal-dialog .btn-primary").contains("Generate Packing Slips").click();
		
		// Wait for completion (modal hides)
		cy.get(".modal-dialog").should("not.exist");
		cy.wait(500); // Give frappe a moment to reload/toast

		// 3. Open Manage / Edit Modal
		cy.get(".page-actions button").contains("Packing Slips").click();
		cy.get(".dropdown-menu a").contains("Manage / Edit").click();

		// Wait for modal
		cy.get(".modal-dialog").should("contain", "Manage Packing Slips (2 Total Boxes)");

		// Assert Draft restrictions
		cy.get(".modal-dialog tbody tr").should("have.length", 2);
		
		cy.get(".modal-dialog tbody tr").first().within(() => {
			// Ensure it has Draft badge
			cy.get(".badge").should("contain", "Draft");
			
			// Ensure it has Delete and Submit buttons with correct classes
			cy.get("button.delete-single-ps").should("exist").and("have.class", "btn-danger");
			cy.get("button.submit-single-ps").should("exist").and("have.class", "btn-primary");
			
			// Ensure Print button does NOT exist
			cy.get("a").contains("Print").should("not.exist");
		});

		// Check for disclaimer
		cy.get(".modal-dialog").should("contain", "Draft Packing Slips cannot be printed");
	});

	it("updates UI state correctly for Submitted slips", () => {
		cy.visit(`/app/delivery-note/${dn_name}`);
		cy.get(".page-actions button").contains("Packing Slips").click();
		cy.get(".dropdown-menu a").contains("Manage / Edit").click();

		cy.get(".modal-dialog").should("be.visible");

		// Click Submit on the first Draft packing slip
		cy.get(".modal-dialog tbody tr").first().within(() => {
			cy.get("button.submit-single-ps").click();
		});

		// Frappe will reload doc and close modal, so we have to wait and reopen
		cy.get(".modal-dialog").should("not.exist");
		cy.wait(1000);

		cy.get(".page-actions button").contains("Packing Slips").click();
		cy.get(".dropdown-menu a").contains("Manage / Edit").click();
		cy.get(".modal-dialog").should("be.visible");

		// Now check the first row is Submitted
		cy.get(".modal-dialog tbody tr").first().within(() => {
			cy.get(".badge").should("contain", "Submitted");
			
			// Submit and Delete buttons should be gone
			cy.get("button.submit-single-ps").should("not.exist");
			
			// Cancel and Print buttons should appear with correct classes
			cy.get("button.cancel-single-ps").should("exist").and("have.class", "btn-danger");
			cy.get("a").contains("Print").should("exist").and("have.class", "btn-primary");
		});
	});

	it("handles Bulk Delete action properly", () => {
		cy.visit(`/app/delivery-note/${dn_name}`);
		cy.get(".page-actions button").contains("Packing Slips").click();
		cy.get(".dropdown-menu a").contains("Manage / Edit").click();

		cy.get(".modal-dialog").should("be.visible");

		// Click Bulk Delete button
		cy.get(".modal-dialog .modal-footer button.btn-danger").contains("Delete All Packing Slips").click();
		
		// Confirm standard JS confirm dialog
		cy.on('window:confirm', () => true);

		// Frappe will close dialog and reload
		cy.get(".modal-dialog").should("not.exist");
		cy.wait(1000);

		// Reopen Manage modal
		cy.get(".page-actions button").contains("Packing Slips").click();
		cy.get(".dropdown-menu a").contains("Manage / Edit").click();
		cy.get(".modal-dialog").should("be.visible");

		// Assert that the Draft slip was deleted, but the Submitted slip remains (1 total box left)
		cy.get(".modal-dialog").should("contain", "Manage Packing Slips (1 Total Boxes)");
		cy.get(".modal-dialog tbody tr").should("have.length", 1);
		cy.get(".modal-dialog tbody tr").first().within(() => {
			cy.get(".badge").should("contain", "Submitted");
		});
		
		// Close modal
		cy.get(".modal-dialog .btn-modal-close").click();
	});
});
