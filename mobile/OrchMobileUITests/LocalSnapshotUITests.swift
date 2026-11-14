import XCTest

/// Owner 14 Nov: "when i open the app it always loads chats and groups new, sometimes all are gone". The last known rows are on
/// disk, so a relaunch shows them at once even when the relay answers slowly.
final class LocalSnapshotUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testRowsAreThereOnRelaunchWhileTheRelayIsSlow() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'room-'")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 15), "the first launch loads the chats")
        Thread.sleep(forTimeInterval: 4)   // the snapshot is written a moment after the last change
        app.terminate()

        // Same install, no reset, and a relay that needs 20 s per call: only the snapshot can fill the list.
        let again = XCUIApplication()
        again.launchArguments = ["-relayMode", "mock", "-mockLatencyMs", "20000"]
        again.launch()
        let rowAgain = again.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'room-'")).firstMatch
        XCTAssertTrue(rowAgain.waitForExistence(timeout: 2), "the chat rows show within 2 s without waiting for the relay")
    }
}
