import XCTest
@testable import OrchMobile

final class TicketResultsTests: XCTestCase {
    private func snapshot(_ object: [String: Any]) throws -> TicketSnapshot {
        try JSONCoding.decoder.decode(TicketSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
    }
    private func item(_ id: String = "j_first1", at: String = "2026-11-11T09:00:00Z") -> [String: Any] {
        ["id": id, "from": "agent", "at": at,
         "doc": ["schema": "orch.blocks/1", "from": "agent", "blocks": [["type": "summary", "text": "Result"]]]]
    }

    func testContractVectors() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/ticket-view-v1.json"))
        let vector = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let cases = try XCTUnwrap(vector["cases"] as? [[String: Any]])
        // Source indices retained, and indices whose documents the renderer refuses.
        let outcomes: [String: (kept: [Int], invalid: Set<Int>)] = [
            "results-trimmed": ([0, 1, 2], []),
            "results-five": ([0, 1, 2, 3, 4], []),
            "results-six": ([0, 1, 2, 3, 4], []),
            "results-in-light": ([], []),
            // Sender-only trimming violations remain valid general block documents.
            "results-log-block": ([0, 1, 2], []),
            "results-table-21-rows": ([0, 1, 2], []),
            "results-link-with-query": ([0, 1, 2], []),
            "results-file-with-folder": ([0, 1, 2], []),
            "results-job-checked": ([0, 2], []),
            "results-from-mismatch": ([0, 2], []),
            "results-unknown-field": ([1, 2], []),
            "results-unknown-schema": ([0, 1, 2], [0]),
            "results-checked-false": ([1, 2], []),
            "results-link-userinfo": ([0, 1, 2], [1])
        ]
        var replayed = Set<String>()
        for fixture in cases {
            let name = try XCTUnwrap(fixture["name"] as? String)
            guard name.hasPrefix("results-") else { continue }
            replayed.insert(name)
            let expected = try XCTUnwrap(outcomes[name], name)
            let message = try XCTUnwrap(fixture["message"] as? [String: Any])
            let body = try XCTUnwrap(message["body"] as? [String: Any])
            let view = try XCTUnwrap(body["ticket_view"] as? [String: Any])
            let source = try XCTUnwrap(view["results"] as? [[String: Any]])
            let decoded = try snapshot(view)
            let ordered = try expected.kept.sorted {
                try XCTUnwrap(TicketResult.date(XCTUnwrap(source[$0]["at"] as? String))) >
                    XCTUnwrap(TicketResult.date(XCTUnwrap(source[$1]["at"] as? String)))
            }
            XCTAssertEqual(decoded.results.map(\.id), ordered.compactMap { source[$0]["id"] as? String }, name)
            if fixture["ok"] as? Bool == true { XCTAssertEqual(decoded.results.count, source.count, name) }
            for (result, index) in zip(decoded.results, ordered) {
                let expectedLabel: String
                switch source[index]["from"] as? String {
                case "job": expectedLabel = "Reported by the job"
                case "agent": expectedLabel = source[index]["checked"] as? Bool == true ? "Checked by the helper" : "From the helper"
                default: expectedLabel = "Worked out by orch"
                }
                XCTAssertEqual(result.label, expectedLabel, name)
                switch result.doc {
                case .invalid: XCTAssertTrue(expected.invalid.contains(index), name)
                case .shown(let doc):
                    XCTAssertFalse(expected.invalid.contains(index), name)
                    for row in doc.rows {
                        if case .link(let block) = row {
                            let url = try XCTUnwrap(URLComponents(string: XCTUnwrap(block.text("url"))))
                            XCTAssertEqual(url.scheme, "https", name)
                            XCTAssertNil(url.user, name); XCTAssertNil(url.password, name)
                        }
                    }
                }
            }
        }
        XCTAssertEqual(replayed, Set(outcomes.keys))
    }

    func testOverlayAndRoundTrip() throws {
        let base = try snapshot(["results": [item()]])
        let light = try snapshot(["light": true, "summary": "New status", "results": [item("j_newone")]])
        XCTAssertTrue(light.results.isEmpty)
        XCTAssertEqual(light.overlaid(on: base).results, base.results)
        XCTAssertTrue(try snapshot([:]).overlaid(on: base).results.isEmpty)
        XCTAssertEqual(try snapshot(["results": [item("j_newone")]]).overlaid(on: base).results.first?.id, "j_newone")
        let encoded = try JSONCoding.encoder.encode(base)
        XCTAssertEqual(try JSONCoding.decoder.decode(TicketSnapshot.self, from: encoded).results, base.results)
        let empty = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(TicketSnapshot())) as? [String: Any])
        XCTAssertNil(empty["results"])
        // Preserve snake-case document keys and unknown keys even in invalid documents.
        var raw = item()
        raw["doc"] = ["schema": "orch.blocks/2", "from": "agent", "total_rows": 40, "custom_key": ["x_y": true]]
        let invalid = try snapshot(["results": [raw]])
        let roundTrip = try JSONCoding.decoder.decode(TicketSnapshot.self, from: JSONCoding.encoder.encode(invalid))
        XCTAssertEqual(roundTrip.results, invalid.results)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: roundTrip.results[0].rawDoc) as? NSDictionary)
        XCTAssertEqual(object, raw["doc"] as? NSDictionary)
        if case .shown = roundTrip.results[0].doc { XCTFail("Invalid doc must stay invalid") }
    }

    func testDeepNestingFailsCleanlyOnBackgroundThread() async throws {
        var deep: Any = 1
        for _ in 0..<500 { deep = [deep] }
        var hostile = item("j_deep001"); hostile["doc"] = ["schema": "orch.blocks/1", "from": "agent",
                                                         "blocks": [["type": "x-new", "v": deep]]]
        let data = try JSONSerialization.data(withJSONObject: ["results": [item("j_before"), hostile]])
        let ids = try await Task.detached { try JSONCoding.decoder.decode(TicketSnapshot.self, from: data).results.map(\.id) }.value
        XCTAssertEqual(ids, ["j_before"])
        var block: Any = 1
        for _ in 0..<500 { block = [block] }
        let doc = try JSONSerialization.data(withJSONObject: ["schema": "orch.blocks/1", "from": "job", "blocks": [["type": "x-new", "v": block]]])
        let shown = await Task.detached { () -> Bool in if case .shown = BlocksResult.decode(doc) { return true }; return false }.value
        XCTAssertFalse(shown, "500-deep doc must not render")
    }

    func testLineSeparatorTitleIsHiddenButResultKept() throws {
        var sep = item("j_title03"); sep["title"] = "Done\u{2028}Checked by the helper"
        var bidi = item("j_title04"); bidi["title"] = "abc\u{202E}def"
        var alm = item("j_title05"); alm["title"] = "abc\u{061C}def"
        let decoded = try snapshot(["results": [sep, bidi, alm]])
        XCTAssertEqual(decoded.results.map(\.id), ["j_title03", "j_title04", "j_title05"])
        XCTAssertTrue(decoded.results.allSatisfy { $0.title == nil })
    }

    func testTitleRulesAndBigNumbers() throws {
        var lined = item("j_title01"); lined["title"] = "A\nChecked by the helper"
        var long = item("j_title02"); long["title"] = String(repeating: "x", count: 201)
        var big = item("j_bignum1"); big["doc"] = ["schema": "orch.blocks/1", "from": "agent", "blocks": [["type": "stat", "label": "Big", "value": 1e200]]]
        let decoded = try snapshot(["results": [lined, long, big]])
        XCTAssertEqual(decoded.results.map(\.id), ["j_bignum1"], "control chars / >200 titles dropped; 1e200 kept")
        if case .invalid = decoded.results[0].doc { XCTFail("1e200 stat must render") }
    }

    func testMalformedItemsDoNotHideValidNeighbors() throws {
        var broken: [Any] = [NSNull(), 42, "bad", [:]]
        for key in ["id", "from", "at", "doc"] {
            var value = item(); value.removeValue(forKey: key); broken.append(value)
        }
        for (key, value) in [("id", "a_"), ("id", "a_bad\n"), ("id", "x_bad"), ("id", "a_" + String(repeating: "x", count: 65)),
                             ("from", "person"), ("at", "yesterday"), ("at", "2026-11-11")] {
            var bad = item(); bad[key] = value; broken.append(bad)
        }
        for value in [false, 1, "true", NSNull()] as [Any] {
            var bad = item(); bad["checked"] = value; broken.append(bad)
        }
        var unknown = item(); unknown["unknown_field"] = true; broken.append(unknown)
        var mismatch = item(); mismatch["from"] = "job"; broken.append(mismatch)
        let decoded = try snapshot(["results": [item("j_before")] + broken + [item("j_after1")]])
        XCTAssertEqual(decoded.results.map(\.id), ["j_before", "j_after1"])
        XCTAssertEqual(decoded.results.first?.label, "From the helper")
    }

    func testFirstDuplicateWinsThenDatesSortAndCap() throws {
        let first = item("j_duplicate", at: "2026-11-11T09:00:00Z")
        let later = item("j_duplicate", at: "2026-11-11T11:00:00Z")
        let offset = item("j_offset1", at: "2026-11-11T10:30:00+02:00")   // schema: UTC "Z" only -> dropped
        let fractional = item("j_fraction", at: "2026-11-11T09:00:00.500Z")
        let decoded = try snapshot(["results": [offset, first, later, fractional]])
        XCTAssertEqual(decoded.results.map(\.id), ["j_fraction", "j_duplicate"])
        XCTAssertEqual(decoded.results[1].at, first["at"] as? String)
        let many = (0..<7).map { item("j_many0\($0)", at: "2026-11-11T0\($0):00:00Z") }
        XCTAssertEqual(try snapshot(["results": many]).results.map(\.id), ["j_many06", "j_many05", "j_many04", "j_many03", "j_many02"])
    }

    func testUnsafeLinksRemainInvalidAndMockDocsRoundTrip() throws {
        for url in ["http://example.com", "javascript:alert(1)", "https://user:pw@example.com"] {
            var raw = item()
            raw["doc"] = ["schema": "orch.blocks/1", "from": "agent",
                          "blocks": [["type": "link", "label": "Open", "url": url]]]
            let result = try XCTUnwrap(snapshot(["results": [raw]]).results.first)
            if case .shown = result.doc { XCTFail("Unsafe link rendered: \(url)") }
        }
        let mock = MockRelay.q3View
        XCTAssertEqual(mock.results.count, 2)
        let restored = try JSONCoding.decoder.decode(TicketSnapshot.self, from: JSONCoding.encoder.encode(mock))
        XCTAssertEqual(restored.results, mock.results)
        for result in restored.results {
            guard case .shown(let doc) = result.doc else { XCTFail("Mock result invalid"); continue }
            if result.from == "job" { XCTAssertTrue(doc.texts.contains("3 of 40 rows")) }
        }
    }

    func testAttachmentMatching() {
        let link = TicketSnapshot.Attachment(kind: "link", name: "chart.png")
        let first = TicketSnapshot.Attachment(kind: "image", blobId: "b_first", name: "CHART.png")
        let second = TicketSnapshot.Attachment(kind: "file", blobId: "b_second", name: "chart.png")
        XCTAssertEqual(TicketResult.attachment(named: "folder/chart.png", in: [link, first, second]), first)
        XCTAssertNil(TicketResult.attachment(named: "missing.png", in: [first]))
    }
}
