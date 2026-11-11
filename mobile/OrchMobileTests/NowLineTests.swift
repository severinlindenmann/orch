import XCTest
@testable import OrchMobile

final class NowLineTests: XCTestCase {
    func testText() {
        XCTAssertEqual(NowLine.text(running: 2, newCount: 1, newFrom: "Home"), "Working on 2 tickets · 1 new from Home")
        XCTAssertEqual(NowLine.text(running: 0, newCount: 3, newFrom: "Home"), "3 new from Home")
        XCTAssertEqual(NowLine.text(running: 2, newCount: 0, newFrom: nil), "Working on 2 tickets")
        XCTAssertNil(NowLine.text(running: 0, newCount: 0, newFrom: nil))
    }
    func testScopedText() {
        XCTAssertEqual(NowLine.scopedText(running: 2, newCount: 1), "Working on 2 tickets · 1 new")
        XCTAssertNil(NowLine.scopedText(running: 0, newCount: 0))
    }
    func testGroupOrderAndHelperStatus() {
        XCTAssertEqual(WorkspaceView.activeOrder, [.waitingOnYou, .review, .working, .paused, .backlog])
        XCTAssertEqual(WorkspaceView.helperStatus(name: "Finance", anyWorking: true, hasMessages: true), "Finance is working")
        XCTAssertEqual(WorkspaceView.helperStatus(name: "Finance", anyWorking: false, hasMessages: true), "Finance is ready")
        XCTAssertNil(WorkspaceView.helperStatus(name: "Finance", anyWorking: false, hasMessages: false))
    }
}
