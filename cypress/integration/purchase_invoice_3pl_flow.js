context("3PL Purchase Invoice Validation", () => {
	before(() => {
		cy.login();
		cy.window().its("frappe").then((frappe) => {
			return frappe.xcall("core_customizations.tests.test_ui_3pl_helpers.setup_cypress_3pl_data");
		});
	});

	it("blocks saving a Purchase Invoice with update_stock for a 3PL item", () => {
		cy.visit("/app/purchase-invoice/new");
		
		// Fill in supplier
		cy.get("div[data-fieldname='supplier'] input").type("Cypress Supplier").blur();
		
        // Check update stock
        cy.get("input[data-fieldname='update_stock']").check({force: true});
        
		// Add item
		cy.get(".grid-add-row").click();
		cy.get(".grid-row-open input[data-fieldname='item_code']").type("Cypress 3PL Item").blur();
        cy.wait(500);
        cy.get(".grid-row-open input[data-fieldname='qty']").clear().type("10").blur();
        cy.get(".grid-row-open input[data-fieldname='rate']").clear().type("100").blur();
		
        // Close grid
        cy.get(".grid-row-open .grid-collapse-row").click();
        
		// Click Save
		cy.get(".page-actions button.primary-action").contains("Save").click();
		
		// Assert error modal appears for update_stock
		cy.get(".msgprint").should("contain", "cannot update stock directly from a Purchase Invoice");
        
        // Close modal
        cy.get(".modal-footer .btn-default").contains("Close").click();
	});
    
	it("blocks saving a Purchase Invoice for a 3PL item without a PR", () => {
		cy.visit("/app/purchase-invoice/new");
		
		// Fill in supplier
		cy.get("div[data-fieldname='supplier'] input").type("Cypress Supplier").blur();
		
		// Ensure update_stock is unchecked for this test
        cy.get("input[data-fieldname='update_stock']").uncheck({force: true});
        
		// Add item
		cy.get(".grid-add-row").click();
		cy.get(".grid-row-open input[data-fieldname='item_code']").type("Cypress 3PL Item").blur();
        cy.wait(500);
        cy.get(".grid-row-open input[data-fieldname='qty']").clear().type("10").blur();
        cy.get(".grid-row-open input[data-fieldname='rate']").clear().type("100").blur();
		
        // Close grid
        cy.get(".grid-row-open .grid-collapse-row").click();
        
		// Click Save
		cy.get(".page-actions button.primary-action").contains("Save").click();
		
		// Assert error modal appears for missing PR
		cy.get(".msgprint").should("contain", "must be billed against a Purchase Receipt");
	});
});
