import XCTest
@testable import OrchMobile

@MainActor
final class VisualFixTests: XCTestCase {
    func testChatTimeFormat() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(secondsFromGMT: 0))
        let now = try XCTUnwrap(ShellTime.date("2026-11-11T16:00:00Z"))
        XCTAssertEqual(ShellTime.short("2026-11-11T14:02:00Z", now: now, calendar: calendar), "14:02")
        XCTAssertEqual(ShellTime.short("2026-10-31T14:02:00Z", now: now, calendar: calendar), "31 Oct")
        XCTAssertEqual(ShellTime.short("2026-11-10T14:02:00Z", now: now, calendar: calendar), "Yesterday")
        XCTAssertEqual(ShellTime.short(nil, now: now, calendar: calendar), "")
    }

    func testTasksWording() {
        XCTAssertEqual(ConversationRules.summaryText(done: 3, total: 3, status: "Ready for review"), "3 of 3 tasks done")
        XCTAssertEqual(ConversationRules.summaryText(done: 1, total: 3, status: "Working"), "1 of 3 tasks done")
        XCTAssertEqual(ConversationRules.summaryText(done: 0, total: 0, status: "Working"), "")
    }

    func testTabCountsKeepReferencePrefixAndOmitZero() {
        XCTAssertEqual(InfoGroup.photos.tabLabel(count: 1), "Photos (1)")
        XCTAssertEqual(InfoGroup.files.tabLabel(count: 1), "Files (1)")
        XCTAssertEqual(InfoGroup.links.tabLabel(count: 4), "References (4)")
        XCTAssertEqual(InfoGroup.artifacts.tabLabel(count: 1), "Artifacts (1)")
        for group in InfoGroup.allCases { XCTAssertEqual(group.tabLabel(count: 0), group.title) }
    }

    func testChatRowPreview() {
        XCTAssertEqual(ChatsRowRules.preview(""), "No messages yet")
        XCTAssertEqual(ChatsRowRules.preview(" \n "), "No messages yet")
        XCTAssertEqual(ChatsRowRules.preview("Allow access?", shownQuestionCount: 1), "1 needs you")
        XCTAssertEqual(ChatsRowRules.preview("Allow access?", shownQuestionCount: 2), "2 need you")
        XCTAssertEqual(ChatsRowRules.preview("Allow access?"), "Allow access?")
        XCTAssertEqual(ChatsRowRules.preview("", starting: true), "Getting started…")
        XCTAssertEqual(ChatsRowRules.preview("Report ready"), "Report ready")
    }
}
