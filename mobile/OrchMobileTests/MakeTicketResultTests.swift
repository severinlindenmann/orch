import XCTest
@testable import OrchMobile

final class MakeTicketResultTests: XCTestCase {
    private func vector() throws -> [String: Any] {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/proposal-result-v1.json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testValidResultsDecodeAndRoundTrip() throws {
        let entries = try XCTUnwrap(vector()["valid"] as? [[String: Any]])
        XCTAssertFalse(entries.isEmpty)
        for entry in entries {
            let message = try XCTUnwrap(entry["message"] as? [String: Any])
            let body = try XCTUnwrap(message["body"] as? [String: Any])
            let expected = try XCTUnwrap(body["proposal_result"] as? [String: String])
            let decoded = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: message))
            let result = try XCTUnwrap(decoded.body.proposalResult)
            XCTAssertEqual(result.result, expected["result"])
            XCTAssertEqual(result.key, expected["key"])
            XCTAssertEqual(result.reason, expected["reason"])
            XCTAssertTrue(decoded.body.isProposalResult)
            let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
            let roundTrip = try JSONCoding.decoder.decode(TextBody.self, from: encoder.encode(decoded.body))
            XCTAssertEqual(roundTrip, decoded.body)
        }
    }

    func testMalformedAndUnknownResultsAreIgnored() throws {
        for marker in ["made", ["result": "future"], ["result": 1], ["result": "made", "key": 1]] as [Any] {
            let data = try JSONSerialization.data(withJSONObject: ["text": "Fallback", "proposal_result": marker])
            let body = try JSONCoding.decoder.decode(TextBody.self, from: data)
            XCTAssertNil(body.proposalResult)
            XCTAssertFalse(body.isProposalResult)
            XCTAssertEqual(body.text, "Fallback")
        }
    }

    func testEveryPhoneVector() throws {
        let entries = try XCTUnwrap(vector()["phone"] as? [[String: Any]])
        XCTAssertFalse(entries.isEmpty)
        for entry in entries {
            var answer: String?
            var answeredAt: Date?
            var now = Date(timeIntervalSince1970: 0)
            var live = true
            var results: [ProposalResult] = []
            let events = try XCTUnwrap(entry["events"] as? [Any])
            for event in events {
                if let event = event as? String {
                    switch event {
                    case "answer_make": answer = "make"; answeredAt = now
                    case "answer_not_now": answer = "not_now"; answeredAt = now
                    case "2_min": now = now.addingTimeInterval(120)
                    case "workspace_not_live": live = false
                    default: XCTFail("Unknown event: \(event)")
                    }
                } else {
                    let result = try XCTUnwrap(event as? [String: Any])
                    if result["reply_to"] as? String == "unknown" { continue }
                    results.append(try JSONCoding.decoder.decode(ProposalResult.self, from: JSONSerialization.data(withJSONObject: result)))
                }
            }
            let state = MakeTicketRules.state(answer: answer, answeredAt: answeredAt, results: results, now: now, workspaceLive: live)
            let card: String
            switch state {
            case .open: card = "open"
            case .making: card = "making"
            case .waiting: card = "waiting"
            case .made: card = "made"
            case .failed: card = "failed"
            case .closed: card = "closed"
            }
            XCTAssertEqual(card, entry["card"] as? String, entry["name"] as? String ?? "")
        }
    }

    func testResultTextsAreHiddenAndNeverUnread() throws {
        for entry in try XCTUnwrap(vector()["valid"] as? [[String: Any]]) {
            let message = try XCTUnwrap(entry["message"] as? [String: Any])
            let text = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: message))
            let pm = PhoneMessage(message: text, workspaceName: "Pilatus Workspace")
            var data = ConversationInputs(); data.messages = [pm]
            let id = ConversationID.general(workspace: text.from)
            XCTAssertNil(ConversationBuilder.conversation(of: pm, nil, data))
            let items = ConversationBuilder.items(id, data)
            XCTAssertTrue(items.isEmpty)
            XCTAssertEqual(ReadState().unread(ReadState.key(id), in: items), 0)
            let summary = ConversationBuilder.general(workspace: text.from, data, read: ReadState())
            XCTAssertEqual(summary.lastLine, "")
            XCTAssertEqual(summary.unread, 0)
            var chat = ChatData(); chat.messages = [pm]
            let legacyItems = ChatBuilder.workspaceItems(text.from, chat)
            XCTAssertTrue(legacyItems.isEmpty)
            XCTAssertEqual(ReadState().unread(ReadState.workspaceKey(text.from), in: legacyItems), 0)
            XCTAssertTrue(ChatBuilder.search(text.body.text, chat, rows: []).messages.isEmpty)
        }
    }

    func testStateDetails() {
        let now = Date()
        XCTAssertEqual(MakeTicketRules.state(answer: nil, answeredAt: nil, results: [], now: now, workspaceLive: true), .open)
        XCTAssertEqual(MakeTicketRules.state(answer: "make", answeredAt: now.addingTimeInterval(-119), results: [], now: now, workspaceLive: true), .making)
        XCTAssertEqual(MakeTicketRules.state(answer: "not_now", answeredAt: now, results: [], now: now, workspaceLive: true), .closed(notNow: true))
        XCTAssertEqual(MakeTicketRules.state(answer: nil, answeredAt: nil,
            results: [ProposalResult(result: "made", key: "PIL-15"), ProposalResult(result: "decided", key: "PIL-16")],
            now: now, workspaceLive: false), .made(key: "PIL-15"))
    }
}
