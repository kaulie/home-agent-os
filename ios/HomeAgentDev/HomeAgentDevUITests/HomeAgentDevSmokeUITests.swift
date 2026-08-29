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
        if app.tabBars.buttons["文档"].waitForExistence(timeout: 2) {
            app.tabBars.buttons["文档"].tap()
            return
        }
        let more = app.tabBars.buttons["More"]
        XCTAssertTrue(more.waitForExistence(timeout: 3), "Docs tab not visible and More overflow missing")
        more.tap()
        let docs = app.staticTexts["文档"].firstMatch
        XCTAssertTrue(docs.waitForExistence(timeout: 3), "Docs entry missing in More menu")
        docs.tap()
    }
}
