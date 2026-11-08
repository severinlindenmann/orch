import XCTest
@testable import OrchMobile

final class ChatDayTests: XCTestCase {
    private var zurich: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Zurich")!
        return calendar
    }

    private func date(_ value: String) -> Date { ISO8601DateFormatter().date(from: value)! }

    func testFourAMWallTimeCutIncludingBothDSTChanges() {
        let cases = [
            ("2026-11-08T03:59:00+01:00", "2026-11-07"),
            ("2026-11-08T04:00:00+01:00", "2026-11-08"),
            ("2026-03-29T01:59:00+01:00", "2026-03-28"),
            ("2026-03-29T03:00:00+02:00", "2026-03-28"),
            ("2026-03-29T03:59:00+02:00", "2026-03-28"),
            ("2026-03-29T04:00:00+02:00", "2026-03-29"),
            ("2026-10-25T02:30:00+02:00", "2026-10-24"),
            ("2026-10-25T02:30:00+01:00", "2026-10-24"),
            ("2026-10-25T03:59:00+01:00", "2026-10-24"),
            ("2026-10-25T04:00:00+01:00", "2026-10-25")
        ]
        for (moment, expected) in cases {
            XCTAssertEqual(ChatDay.key(for: date(moment), calendar: zurich), expected, moment)
        }
    }

    private func message(_ body: TextBody, from: String = "ws_a", ticket: String? = nil) -> PhoneMessage {
        PhoneMessage(message: TextMessage(id: "m_1", from: from, to: from == "ws_a" ? "ph_1" : "ws_a", type: "text",
            createdAt: "2026-11-08T12:00:00Z", ticket: ticket, body: body), workspaceName: "A")
    }

    func testMetadataDecodesAndBuilderUsesDayAndAuthorOnlyForChat() throws {
        let body = try JSONDecoder().decode(TextBody.self, from: Data(#"{"text":"Hello","general":true,"by":"you","via":"dashboard","phone":"ph_2","day":"2026-11-07"}"#.utf8))
        XCTAssertEqual(body.by, "you"); XCTAssertEqual(body.via, "dashboard")
        XCTAssertEqual(body.phone, "ph_2"); XCTAssertEqual(body.day, "2026-11-07")
        var input = ConversationInputs(messages: [message(body)])
        let item = try XCTUnwrap(ConversationBuilder.items(.general(workspace: "ws_a"), input).first)
        XCTAssertEqual(item.side, .me)
        XCTAssertEqual(item.by, "you")
        XCTAssertEqual(ChatDay.key(of: item, calendar: zurich), "2026-11-07")
        var helper = body; helper.by = "ws_a"
        input.messages = [message(helper, from: "ph_1")]
        XCTAssertEqual(ConversationBuilder.items(.general(workspace: "ws_a"), input).first?.side, .them)
        input.messages = [message(body, ticket: "t_1")]
        let ticketItem = try XCTUnwrap(ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), input).first)
        XCTAssertEqual(ticketItem.side, .them); XCTAssertNil(ticketItem.by); XCTAssertNil(ticketItem.day)
    }

    func testOldMessagesAndOutgoingEncoding() throws {
        let body = try JSONDecoder().decode(TextBody.self, from: Data(#"{"text":"Hello","general":true}"#.utf8))
        XCTAssertNil(body.by); XCTAssertNil(body.via); XCTAssertNil(body.phone); XCTAssertNil(body.day)
        XCTAssertEqual(ChatDay.side(by: nil, fromPhone: true), .me)
        XCTAssertEqual(ChatDay.side(by: nil, fromPhone: false), .them)
        XCTAssertEqual(ChatDay.side(by: "you", fromPhone: false), .me)
        XCTAssertEqual(ChatDay.side(by: "ws_a", fromPhone: true), .them)
        XCTAssertEqual(try JSONDecoder().decode(TextBody.self, from: JSONEncoder().encode(body)), body)
        var incoming = body
        incoming.by = "you"; incoming.via = "phone"; incoming.phone = "ph_1"; incoming.day = "2026-11-08"
        let encoded = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(incoming)) as? [String: Any])
        for field in ["by", "via", "phone", "day"] { XCTAssertNil(encoded[field]) }
        let input = ConversationInputs(messages: [message(body, from: "ph_1")])
        XCTAssertNil(ConversationBuilder.items(.general(workspace: "ws_a"), input).first?.day)
    }

    func testAcknowledgementSuppliesThePhoneTextsDay() throws {
        let own = message(TextBody(text: "Hello", general: true), from: "ph_1")
        var ackBody = TextBody(update: TextUpdate(kind: "ack"), general: true)
        ackBody.day = "2026-11-07"
        let ack = PhoneMessage(message: TextMessage(id: "m_ack", from: "ws_a", to: "ph_1", type: "text",
            createdAt: "2026-11-08T12:01:00Z", ticket: nil, body: ackBody, replyTo: own.id), workspaceName: "A")
        let items = ConversationBuilder.items(.general(workspace: "ws_a"), ConversationInputs(messages: [own, ack]))
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.day, "2026-11-07")
        XCTAssertEqual(items.first?.side, .me)
        let oldHelper = ConversationBuilder.items(.general(workspace: "ws_a"), ConversationInputs(messages: [message(TextBody(text: "Hello"))]))
        XCTAssertEqual(oldHelper.first?.side, .them)
        XCTAssertNil(oldHelper.first?.by)
    }

    func testQueuedChatWording() {
        XCTAssertEqual(ChatDay.queuedNote, "Waiting · will send when online")
    }

    func testSplitLabelsAndSearch() {
        func item(_ id: String, _ day: String, _ text: String) -> ConvItem {
            ConvItem(id: id, at: "2026-11-08T12:00:00Z", side: .them, day: day, text: text)
        }
        let items = [item("a", "2026-11-06", "Car TAX"), item("b", "2026-11-07", "Budget"),
                     item("c", "2026-11-06", "Paid"), item("d", "2026-11-08", "Hello")]
        let split = ChatDay.split(items, today: "2026-11-08")
        XCTAssertEqual(split.past.map(\.day), ["2026-11-06", "2026-11-07"])
        XCTAssertEqual(split.past[0].items.map(\.id), ["a", "c"])
        XCTAssertEqual(split.today.map(\.id), ["d"])
        XCTAssertEqual(ChatDay.search(split.past, "tax").map(\.day), ["2026-11-06"])
        XCTAssertEqual(ChatDay.search(split.past, " ").count, 2)
        XCTAssertTrue(ChatDay.search(split.past, "missing").isEmpty)
        XCTAssertEqual(ChatDay.label(forDay: "2026-11-08", today: "2026-11-08"), "Today")
        XCTAssertEqual(ChatDay.label(forDay: "2026-11-07", today: "2026-11-08"), "Yesterday")
        XCTAssertEqual(ChatDay.label(forDay: "2025-11-03", today: "2026-11-08"), "Mon 3 Nov")
    }
}
