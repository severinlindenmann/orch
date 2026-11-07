import XCTest
@testable import OrchMobile

final class ConversationViewTests: XCTestCase {
    func testClockTextHasTwoDigitMinutes() {
        XCTAssertEqual(clockText(1), "00:01")
        XCTAssertEqual(clockText(5.9), "00:05")
        XCTAssertEqual(clockText(90), "01:30")
        XCTAssertEqual(clockText(-3), "00:00")
        XCTAssertEqual(clockText(.nan), "00:00")
    }
}
