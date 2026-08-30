import XCTest

/// P0 smoke: reach Docs tab and load the project Markdown index (needs reachable Dev Brain).
final class HomeAgentDevSmokeUITests: XCTestCase {
    func testDocsTabShowsProjectMarkdownList() throws {
        let app = XCUIApplication()
        app.launch()

        openDocsTab(in: app)

        let list = app.descendants(matching: .any)["dev.docs.list"]
        XCTAssertTrue(list.waitForExistence(timeout: 20), "Docs list should load from Brain /api/v1/admin/docs")
    }

    private func openDocsTab(in app: XCUIApplication) {
        let docsTab = app.tabBars.buttons["文档"]
        XCTAssertTrue(docsTab.waitForExistence(timeout: 5), "Docs tab should be on main tab bar")
        docsTab.tap()
    }
}
