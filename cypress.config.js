// Do NOT require("cypress") here — Cypress is installed in the bench root's
// node_modules, not inside the app directory. A plain export works with any
// Cypress v10+ runner without needing the package to be locally resolvable.
module.exports = {
  e2e: {
    setupNodeEvents(on, config) {
      // implement node event listeners here
    },
    specPattern: "cypress/integration/**/*.js",
    supportFile: false,
  },
};
