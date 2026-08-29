import XCTest

/// @quality gate #340 / #343 — Markdown reader smoke (sha 7042b16).
final class MarkdownReaderUITests: XCTestCase {
    private let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
        app.launch()
    }

    func testDocsTabOpenScrollAndReaderChrome() throws {
        openDocsTab()

        let list = app.descendants(matching: .any)["dev.docs.list"]
        XCTAssertTrue(list.waitForExistence(timeout: 15), "Docs list did not load (Brain/docs API?)")

        let row = app.descendants(matching: .any)["dev.docs.row.docs.architecture.presentation-cleanup.md"]
        if !row.waitForExistence(timeout: 5) {
            let search = app.searchFields.firstMatch
            if search.waitForExistence(timeout: 3) {
                search.tap()
                search.typeText("presentation-cleanup")
            }
            XCTAssertTrue(row.waitForExistence(timeout: 8), "presentation-cleanup doc row missing")
        }
        row.tap()

        let reader = app.descendants(matching: .any)["dev.docs.detail"]
        if !reader.waitForExistence(timeout: 20) {
            let heading = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Presentation'")).firstMatch
            XCTAssertTrue(heading.waitForExistence(timeout: 5), "Markdown reader did not appear")
        }

        if reader.waitForExistence(timeout: 3) {
            reader.swipeUp()
            reader.swipeUp()
        } else {
            app.swipeUp()
            app.swipeUp()
        }

        let toc = app.buttons["dev.markdown.toc"]
        if !toc.waitForExistence(timeout: 5) {
            // Toolbar icon may expose as label "目录"
            let tocLabel = app.buttons["目录"]
            XCTAssertTrue(tocLabel.waitForExistence(timeout: 3), "TOC button missing")
        }
    }

    func testChatInlineDocLinkOpensReader() throws {
        app.tabBars.buttons["Chat"].tap()
        let link = app.links["📄 presentation-cleanup.md"].firstMatch
        if !link.waitForExistence(timeout: 20) {
            let alt = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'presentation-cleanup'")).firstMatch
            XCTAssertTrue(alt.waitForExistence(timeout: 15), "Chat doc link not found (message #349?)")
            alt.tap()
        } else {
            link.tap()
        }
        XCTAssertTrue(
            app.descendants(matching: .any)["dev.docs.detail"].waitForExistence(timeout: 15) ||
                app.navigationBars.matching(NSPredicate(format: "identifier CONTAINS 'presentation' OR label CONTAINS 'presentation'")).firstMatch.waitForExistence(timeout: 5),
            "InlineDocSheet reader did not open"
        )
        XCTAssertTrue(app.buttons["dev.markdown.toc"].waitForExistence(timeout: 8) || app.buttons["目录"].waitForExistence(timeout: 3))
    }

    func testFontScalePersistsViaAppStorage() throws {
        openPresentationCleanupDoc()

        let larger = app.buttons["dev.markdown.font.larger"]
        let label = app.staticTexts["dev.markdown.font.label"]
        XCTAssertTrue(larger.waitForExistence(timeout: 8))
        XCTAssertTrue(label.waitForExistence(timeout: 3))
        let before = label.label

        for _ in 0..<3 { larger.tap() }
        let scaled = label.label
        XCTAssertNotEqual(before, scaled, "Font scale label should change after A+")

        app.terminate()
        app.launch()

        openPresentationCleanupDoc()
        let afterRelaunch = app.staticTexts["dev.markdown.font.label"]
        XCTAssertTrue(afterRelaunch.waitForExistence(timeout: 10))
        XCTAssertEqual(afterRelaunch.label, scaled, "Font scale should persist (@AppStorage)")
    }

    func testTOCJumpToHeading() throws {
        openPresentationCleanupDoc()

        let toc = app.buttons["dev.markdown.toc"]
        XCTAssertTrue(toc.waitForExistence(timeout: 8))
        toc.tap()

        let sheet = app.navigationBars["目录"]
        if !sheet.waitForExistence(timeout: 5) {
            XCTAssertTrue(app.otherElements["dev.markdown.toc.sheet"].waitForExistence(timeout: 2), "TOC sheet missing")
        }

        let item = app.buttons["dev.markdown.toc.item.1"]
        if !item.waitForExistence(timeout: 5) {
            XCTAssertTrue(app.buttons["dev.markdown.toc.item.0"].waitForExistence(timeout: 3), "Expected outline entries")
            app.buttons["dev.markdown.toc.item.0"].tap()
        } else {
            item.tap()
        }

        XCTAssertTrue(app.descendants(matching: .any)["dev.docs.detail"].waitForExistence(timeout: 5))
    }

    private func openDocsTab() {
        let docsTab = app.tabBars.buttons["文档"]
        if docsTab.waitForExistence(timeout: 2) {
            docsTab.tap()
            return
        }
        let more = app.tabBars.buttons["More"]
        if more.waitForExistence(timeout: 3) {
            more.tap()
            let docsText = app.staticTexts["文档"].firstMatch
            if docsText.waitForExistence(timeout: 3) {
                docsText.tap()
                return
            }
            let docsCell = app.cells.containing(.staticText, identifier: "文档").firstMatch
            if docsCell.waitForExistence(timeout: 2) {
                docsCell.tap()
                return
            }
        }
        XCTFail("Cannot find Docs tab (tab bar or More overflow)")
    }

    private func openPresentationCleanupDoc() {
        openDocsTab()
        let row = app.descendants(matching: .any)["dev.docs.row.docs.architecture.presentation-cleanup.md"]
        if row.waitForExistence(timeout: 12) {
            row.tap()
            XCTAssertTrue(app.descendants(matching: .any)["dev.docs.detail"].waitForExistence(timeout: 20) ||
            app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Presentation'")).firstMatch.waitForExistence(timeout: 5))
            return
        }
        let search = app.searchFields.firstMatch
        if search.waitForExistence(timeout: 3) {
            search.tap()
            search.typeText("presentation-cleanup")
        }
        XCTAssertTrue(row.waitForExistence(timeout: 8))
        row.tap()
        XCTAssertTrue(app.descendants(matching: .any)["dev.docs.detail"].waitForExistence(timeout: 20) ||
            app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Presentation'")).firstMatch.waitForExistence(timeout: 5))
    }
}
