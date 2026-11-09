import XCTest
@testable import OrchMobile

final class WontDoTests: XCTestCase {
    private func task(_ json: String) throws -> TicketSnapshot.Task {
        try JSONCoding.decoder.decode(TicketSnapshot.Task.self, from: Data(json.utf8))
    }

    func testDecodeWontDoWithReason() throws {
        let decoded = try task(#"{"text":"Email finance","done":false,"wont_do":true,"reason":"Finance pulls it themselves"}"#)
        XCTAssertFalse(decoded.done)
        XCTAssertTrue(decoded.wontDo)
        XCTAssertEqual(decoded.reason, "Finance pulls it themselves")
    }

    func testMissingDoneAndReason() throws {
        let decoded = try task(#"{"text":"Email finance","wont_do":true}"#)
        XCTAssertFalse(decoded.done)
        XCTAssertTrue(decoded.wontDo)
        XCTAssertNil(decoded.reason)
    }

    func testDoneWinsAndDropsReason() throws {
        let decoded = try task(#"{"text":"Email finance","done":true,"wont_do":true,"reason":"Skipped"}"#)
        XCTAssertTrue(decoded.done)
        XCTAssertFalse(decoded.wontDo)
        XCTAssertNil(decoded.reason)
    }

    func testReasonWithoutWontDoIsDropped() throws {
        let decoded = try task(#"{"text":"Email finance","reason":"Skipped"}"#)
        XCTAssertFalse(decoded.wontDo)
        XCTAssertNil(decoded.reason)
    }

    func testMalformedOptionalValuesAreLenient() throws {
        let decoded = try task(#"{"text":"Email finance","done":"yes","wont_do":"yes","reason":42}"#)
        XCTAssertFalse(decoded.done)
        XCTAssertFalse(decoded.wontDo)
        XCTAssertNil(decoded.reason)
        let skipped = try task(#"{"text":"Email finance","done":null,"wont_do":true,"reason":42}"#)
        XCTAssertTrue(skipped.wontDo)
        XCTAssertNil(skipped.reason)
    }

    func testRoundTripAndOmittedKeys() throws {
        let original = TicketSnapshot.Task(text: "Email finance", wontDo: true, reason: "Nobody uses it")
        let data = try JSONCoding.encoder.encode(original)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["wont_do"] as? Bool, true)
        XCTAssertEqual(object["reason"] as? String, "Nobody uses it")
        XCTAssertEqual(try JSONCoding.decoder.decode(TicketSnapshot.Task.self, from: data), original)
        for item in [TicketSnapshot.Task(text: "Open"), .init(text: "Done", done: true), .init(text: "Skipped", wontDo: true)] {
            let encoded = try JSONCoding.encoder.encode(item)
            let keys = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
            XCTAssertNil(keys["reason"])
            if !item.wontDo { XCTAssertNil(keys["wont_do"]) }
            XCTAssertEqual(try JSONCoding.decoder.decode(TicketSnapshot.Task.self, from: encoded), item)
        }
        let snapshot = TicketSnapshot(checklist: [original, .init(text: "Done", done: true), .init(text: "Open")])
        XCTAssertEqual(snapshot.done, 1)
        XCTAssertEqual(snapshot.wontDo, 1)
        XCTAssertEqual(snapshot.totalCount, 3)
        let stored = try JSONCoding.encoder.encode(snapshot)
        XCTAssertEqual(try JSONCoding.decoder.decode(TicketSnapshot.self, from: stored), snapshot)
    }

    func testFallbackCountsResolvedSteps() throws {
        let data = Data(#"{"checklist":[{"text":"Done","done":true},{"text":"Skipped","wont_do":true},{"text":"Open"}]}"#.utf8)
        let snapshot = try JSONCoding.decoder.decode(TicketSnapshot.self, from: data)
        XCTAssertNil(snapshot.done)
        XCTAssertEqual(snapshot.doneCount, 1)
        XCTAssertEqual(snapshot.wontDoCount, 1)
    }

    func testSummary() {
        XCTAssertEqual(ConversationRules.summaryText(done: 1, total: 3, status: "Done", wontDo: 2), "1 of 3 done, 2 won't do")
        XCTAssertEqual(ConversationRules.summaryText(done: 2, total: 3, status: "Working", wontDo: 0), "2 of 3 steps done")
        XCTAssertEqual(ConversationRules.summaryText(done: 0, total: 3, status: "Working", wontDo: 2), "0 of 3 done, 2 won't do")
    }

    func testContractVector() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/ticket-view-v1.json"))
        let vector = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let cases = try XCTUnwrap(vector["cases"] as? [[String: Any]])
        let shape = try XCTUnwrap(cases.first { $0["name"] as? String == "wont-do-step" })
        let message = try XCTUnwrap(shape["message"] as? [String: Any])
        let body = try XCTUnwrap(message["body"] as? [String: Any])
        let view = try XCTUnwrap(body["ticket_view"] as? [String: Any])
        let snapshot = try JSONCoding.decoder.decode(TicketSnapshot.self, from: JSONSerialization.data(withJSONObject: view))
        XCTAssertEqual(snapshot.checklist.map(\.wontDo), [false, true, true])
        XCTAssertEqual(snapshot.checklist.count, 3)
        XCTAssertEqual(snapshot.checklist.dropFirst().first?.reason, "Finance pulls it themselves")
        XCTAssertEqual(snapshot.doneCount, 1)
        XCTAssertEqual(snapshot.wontDo, 2)
        XCTAssertEqual(snapshot.wontDoCount, 2)
    }

    func testOlderViewWithoutWontDoCountStillDecodes() throws {
        let data = Data(#"{"checklist":[{"text":"Done","done":true},{"text":"Skipped","wont_do":true}],"done":1,"total":2}"#.utf8)
        let snapshot = try JSONCoding.decoder.decode(TicketSnapshot.self, from: data)
        XCTAssertNil(snapshot.wontDo)
        XCTAssertEqual(snapshot.wontDoCount, 1)
        let negative = try JSONCoding.decoder.decode(TicketSnapshot.self, from: Data(#"{"checklist":[],"done":1,"wont_do":-1,"total":3}"#.utf8))
        XCTAssertNil(negative.wontDo)
    }
}
