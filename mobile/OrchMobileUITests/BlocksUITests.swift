import XCTest

@MainActor
final class BlocksUITests: XCTestCase {
    func testAllTenPreview() {
        let app = XCUIApplication()
        app.launchArguments = ["-blocksPreview", "valid-all-ten"]
        app.launch()
        XCTAssertTrue(app.otherElements["blocks-view"].waitForExistence(timeout: 10))
        for text in ["Invoice export", "Upload", "No network"] {
            XCTAssertTrue(app.staticTexts[text].exists, text)
        }
    }

    func testInvalidPreview() {
        let app = XCUIApplication()
        app.launchArguments = ["-blocksPreview", "invalid-link-javascript"]
        app.launch()
        XCTAssertTrue(app.staticTexts["These results can't be shown"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.otherElements["blocks-invalid"].exists)
    }
}
