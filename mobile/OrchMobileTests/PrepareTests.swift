import XCTest
@testable import OrchMobile

/// ORCH-742 (look B): Preparing / Prepared under the title and the What I found row on the phone.
final class PrepareTests: XCTestCase {
    private func snapshot(_ object: [String: Any]) throws -> TicketSnapshot {
        try JSONCoding.decoder.decode(TicketSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
    }
    private let found: [String: Any] = [
        "sources": [
            ["name": "MKT-214 Spring newsletter", "link": "https://acme.example/browse/MKT-214", "opened": true, "lines": "One mail, four photos."],
            ["name": "Old notes", "link": "javascript:alert(1)", "opened": true],
            ["name": 7, "opened": true],
            ["name": "Email from Anna", "opened": false, "why": "No mail connection is set up."],
        ],
        "facts": ["For 1,400 shop customers", 3],
        "at": "2026-11-19T09:41:00Z",
    ]

    func testMarkOnlyWhileSavedInBacklog() throws {
        XCTAssertEqual(PrepareRules.mark(try snapshot(["title": "T", "status": "open", "prepare": ["state": "preparing"]])), .preparing)
        XCTAssertEqual(PrepareRules.mark(try snapshot(["title": "T", "status": "open", "prepare": ["state": "waiting"]])), .preparing)
        XCTAssertEqual(PrepareRules.mark(try snapshot(["title": "T", "status": "open", "prepare": ["state": "prepared", "at": "2026-11-19T09:41:00Z"]])), .prepared)
        XCTAssertNil(PrepareRules.mark(try snapshot(["title": "T", "status": "open", "prepare": ["state": "not_prepared"]])))
        XCTAssertNil(PrepareRules.mark(try snapshot(["title": "T", "status": "active", "prepare": ["state": "prepared"]])), "gone once it started")
        XCTAssertNil(PrepareRules.mark(try snapshot(["title": "T", "status": "open", "prepare": "odd"])))
        XCTAssertEqual(PrepareRules.word(.prepared), "☰ Prepared")
        XCTAssertEqual(PrepareRules.word(.preparing), "Preparing")
    }

    func testFoundDecodesLenientlyAndCountsTheRow() throws {
        let view = try snapshot(["title": "T", "status": "open", "found": found])
        let f = try XCTUnwrap(view.found)
        XCTAssertEqual(f.sources.map(\.name), ["MKT-214 Spring newsletter", "Old notes", "Email from Anna"], "one bad source never hides the others")
        XCTAssertEqual(f.facts, ["For 1,400 shop customers"])
        XCTAssertEqual(f.read.first?.webURL?.absoluteString, "https://acme.example/browse/MKT-214")
        XCTAssertNil(f.read[1].webURL, "only web addresses open")
        let row = try XCTUnwrap(PrepareRules.foundRow(f))
        XCTAssertEqual(row.count, "2 sources")
        XCTAssertEqual(row.closed, "1 could not be opened")
        XCTAssertNil(PrepareRules.foundRow(TicketFound()))
        XCTAssertEqual(PrepareRules.foundRow(TicketFound(sources: [.init(name: "Mail", opened: false)]))?.count, "Nothing read")
    }

    func testPrepareAndFoundSurviveTheLocalCache() throws {
        let view = try snapshot(["title": "T", "status": "open", "prepare": ["state": "prepared"], "found": found])
        let back = try JSONCoding.decoder.decode(TicketSnapshot.self, from: JSONCoding.encoder.encode(view))
        XCTAssertEqual(back.prepare, view.prepare)
        XCTAssertEqual(back.found, view.found)
    }
}
