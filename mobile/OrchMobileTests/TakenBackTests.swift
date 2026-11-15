import XCTest
@testable import OrchMobile

final class TakenBackTests: XCTestCase {
    private func vector() throws -> [String: Any] {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/taken-back-v1.json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func question(_ id: String, from: String = "ws_pilatus001") throws -> Question {
        let json: [String: Any] = ["workspace_name": "Pilatus Workspace", "message": [
            "schema": "orch.msg/1", "id": id, "from": from, "to": "phones", "type": "question", "created_at": "2026-11-15T09:00:00Z",
            "ticket": "t_7k3f9q", "body": ["question_id": "q1", "text": "Which one?", "options": ["A", "B"]]]]
        return try JSONCoding.decoder.decode(Question.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func takenBackText(_ message: [String: Any]) throws -> PhoneMessage {
        let text = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: message))
        return PhoneMessage(message: text, workspaceName: "Pilatus Workspace")
    }

    func testValidTextsDecodeAndRoundTrip() throws {
        let entries = try XCTUnwrap(vector()["valid"] as? [[String: Any]])
        XCTAssertFalse(entries.isEmpty)
        for entry in entries {
            let message = try XCTUnwrap(entry["message"] as? [String: Any])
            let body = try XCTUnwrap(message["body"] as? [String: Any])
            let expected = try XCTUnwrap((body["taken_back"] as? [String: Any])?["reason"] as? String)
            let decoded = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: message))
            XCTAssertEqual(decoded.body.takenBack?.reason, expected)
            XCTAssertTrue(decoded.body.isTakenBack)
            XCTAssertTrue(decoded.body.isSilentResult)
            let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
            let roundTrip = try JSONCoding.decoder.decode(TextBody.self, from: encoder.encode(decoded.body))
            XCTAssertEqual(roundTrip, decoded.body)
        }
    }

    func testMalformedMarkerIsNotATakeBack() throws {
        for marker in ["gone", ["reason": 1], ["reason": ""]] as [Any] {
            let data = try JSONSerialization.data(withJSONObject: ["text": "Taken back: x", "taken_back": marker])
            let body = try JSONCoding.decoder.decode(TextBody.self, from: data)
            XCTAssertFalse(body.isTakenBack)
        }
    }

    func testEveryPhoneVector() throws {
        let root = try vector()
        let entries = try XCTUnwrap(root["phone"] as? [[String: Any]])
        let valid = try XCTUnwrap((root["valid"] as? [[String: Any]])?.first?["message"] as? [String: Any])
        XCTAssertFalse(entries.isEmpty)
        for entry in entries {
            let name = entry["name"] as? String ?? "?"
            let shown = try XCTUnwrap(entry["shown"] as? [String]).map { try question($0) }
            var messages: [PhoneMessage] = []
            var refused = Set<String>(), shows: String?
            for event in try XCTUnwrap(entry["events"] as? [[String: Any]]) {
                if let t = event["taken_back"] as? [String: Any] {
                    var m = valid
                    m["reply_to"] = t["reply_to"]; m["id"] = "m_tb\(messages.count)"
                    messages.append(try takenBackText(m))
                } else if let a = event["answer_409"] as? [String: Any] {
                    refused.insert(try XCTUnwrap(a["reply_to"] as? String))
                    shows = a["message"] as? String
                } else { XCTFail("Unknown event in \(name)") }
            }
            let cards = TakenBackRules.open(shown, messages: messages, refused: refused).map(\.id)
            XCTAssertEqual(cards, entry["cards"] as? [String], name)
            // no bubble, never unread
            for pm in messages {
                var data = ConversationInputs(); data.messages = [pm]
                let id = ConversationID.general(workspace: pm.message.from)
                let items = ConversationBuilder.items(id, data)
                XCTAssertTrue(items.isEmpty, name)
                XCTAssertEqual(ReadState().unread(ReadState.key(id), in: items), 0, name)
                var chat = ChatData(); chat.messages = [pm]
                XCTAssertTrue(ChatBuilder.workspaceItems(pm.message.from, chat).isEmpty, name)
            }
            XCTAssertEqual(entry["bubble"] as? Bool, false); XCTAssertEqual(entry["unread"] as? Int, 0)
            if let want = entry["shows"] as? String { XCTAssertEqual(shows, want, name) }
        }
    }

    func testTextFromAnotherWorkspaceOrPhoneClosesNothing() throws {
        var m = try XCTUnwrap(vector()["valid"] as? [[String: Any]])[0]["message"] as! [String: Any]
        m["reply_to"] = "m_tq00000000000001"
        m["from"] = "ws_other00001"
        let q = try question("m_tq00000000000001")
        XCTAssertEqual(TakenBackRules.open([q], messages: [try takenBackText(m)]).count, 1)
    }

    /// The relay's `409 taken_back` on a queued answer: the card goes and the relay's own line is kept.
    @MainActor func testRefusedAnswerEventCarriesTheRelayLine() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("tb-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let q = try await relay.questions()[0]
        await relay.takeBack(q.id, reason: "plans changed", sendText: false)
        let item = ob.enqueueAnswer(question: q, answer: "Yes")
        let events = await ob.flush(using: relay)
        XCTAssertEqual(events, [.questionTakenBack(clientId: item.clientId, questionMessageId: q.id,
                                                    message: "This question was taken back: plans changed")])
        XCTAssertTrue(ob.items.isEmpty)
        let open = try await relay.questions()
        XCTAssertFalse(open.contains { $0.id == q.id })
    }
}
