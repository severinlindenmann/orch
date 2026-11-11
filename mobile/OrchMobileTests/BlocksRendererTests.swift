import XCTest
@testable import OrchMobile

final class BlocksRendererTests: XCTestCase {
    func testSnakeCaseKeysSurviveDecoding() throws {
        let raw = #"{"schema":"orch.blocks/1","from":"orch","blocks":[{"type":"table","columns":[{"key":"due_date","label":"Due"}],"rows":[{"due_date":"tomorrow"}],"total_rows":7},{"type":"chart","kind":"line","x_label":"Day","series":[{"name":"S","points":[[1,2]]}]}]}"#
        guard case .shown(let doc) = BlocksResult.decode(Data(raw.utf8)) else { return XCTFail("valid doc refused") }
        XCTAssertTrue(doc.texts.contains("tomorrow"), "\(doc.texts)")
        XCTAssertTrue(doc.texts.contains("1 of 7 rows"), "\(doc.texts)")
        XCTAssertTrue(doc.texts.contains("Day"), "\(doc.texts)")
    }

    func testContractVectors() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let folder = root.appendingPathComponent("contracts/vectors/blocks")
        let files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        XCTAssertFalse(files.isEmpty, "The shared blocks vectors must exist")
        for file in files {
            let vector = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
            let doc = try XCTUnwrap(vector["doc"] as? [String: Any])
            let valid = try XCTUnwrap(vector["valid"] as? Bool)
            let shows = try XCTUnwrap(vector["shows"] as? [String])
            let fallback = try XCTUnwrap(vector["fallback"] as? Int)
            // Exercise both entry points against every fixture.
            for result in [BlocksResult.decode(doc), BlocksResult.decode(try JSONSerialization.data(withJSONObject: doc))] {
                switch result {
                case .shown(let rendered):
                    XCTAssertTrue(valid, file.lastPathComponent)
                    for text in shows {
                        XCTAssertTrue(rendered.texts.contains { $0.contains(text) }, "\(file.lastPathComponent): missing \(text)")
                    }
                    XCTAssertEqual(rendered.fallbackCount, fallback, file.lastPathComponent)
                case .invalid:
                    XCTAssertFalse(valid, file.lastPathComponent)
                }
            }
        }
    }

    private func document(_ blocks: [[String: Any]], title: Any? = nil) -> [String: Any] {
        var doc: [String: Any] = ["schema": "orch.blocks/1", "from": "job", "blocks": blocks]
        if let title { doc["title"] = title }
        return doc
    }
    private func assertInvalid(_ doc: [String: Any], file: StaticString = #filePath, line: UInt = #line) {
        if case .shown = BlocksResult.decode(doc) { XCTFail("Expected invalid document", file: file, line: line) }
    }
    func testLiteralTextAndUnknownVersion() {
        let doc = document([["type": "summary", "text": "<b>x</b>"]])
        guard case .shown(let shown) = BlocksResult.decode(doc) else { return XCTFail("Valid literal text") }
        XCTAssertTrue(shown.texts.contains("<b>x</b>"))
        var newer = doc; newer["schema"] = "orch.blocks/2"; assertInvalid(newer)
    }
    func testLimitsAndJSONTypes() {
        assertInvalid(document(Array(repeating: ["type": "new-type"], count: 51)))
        assertInvalid(document([["type": "new-type", "payload": String(repeating: "x", count: 65_536)]]))
        assertInvalid(document([], title: NSNull()))
        assertInvalid(document([], title: String(repeating: "a", count: 201)))
        assertInvalid(document([["type": "summary", "text": ""]]))
        assertInvalid(document([["type": "summary", "text": String(repeating: "a", count: 2001)]]))
        assertInvalid(document([["type": "progress", "label": "Work", "done": true, "total": 10]]))
        assertInvalid(document([["type": "progress", "label": "Work", "done": 0, "total": 0]]))
        assertInvalid(document([["type": "stat", "label": "Work", "value": NSNull()]]))
        assertInvalid(document([["type": "stat", "label": "Work", "value": 1, "tone": "green"]]))
        assertInvalid(document([["type": "steps", "items": [["label": "A", "state": "done", "extra": 1]]]]))
        assertInvalid(document([["type": "steps", "items": []]]))
        assertInvalid(document([["type": "kv", "items": [["key": "A", "value": false]]]]))
        assertInvalid(document([["type": "log", "lines": ["a\nb"]]]))
        assertInvalid(document([["type": "log", "lines": [], "cut": 0.5]]))
        assertInvalid(document([["type": "chart", "kind": "pie", "series": []]]))
        assertInvalid(document([["type": "chart", "kind": "line", "series": [["name": "A", "points": [[1, true]]]]]]))
        assertInvalid(document([["type": "new_type"]]))
        var extra = document([]); extra["extra"] = 1; assertInvalid(extra)
    }
    func testFilePathsAndLinks() {
        for path in ["C:/foo", "a\\b", "a/.hidden/x", ".orch/tickets/t_abc123/artifacts/.env", ".orch/tickets/t_abc123/artifacts/", ".orch/tickets/no/artifacts/x"] {
            assertInvalid(document([["type": "file", "path": path]]))
        }
        for url in ["https://", "https://user@example.com", "https://example.com/a b", "https://example.com/<b>"] {
            assertInvalid(document([["type": "link", "url": url, "label": "Link"]]))
        }
    }
    func testSharedFormattingAndTableKeys() {
        let doc = document([
            ["type": "progress", "label": "Files", "done": 12, "total": 40, "unit": "files"],
            ["type": "stat", "label": "Rows", "value": 1204],
            ["type": "table", "columns": [["key": "elapsed_time", "label": "Time", "kind": "duration"]],
             "rows": [["elapsed_time": 65]], "total_rows": 2000],
            ["type": "file", "path": "reports/output.csv", "size": 1024]
        ])
        guard case .shown(let shown) = BlocksResult.decode(doc) else { return XCTFail("Valid document") }
        for text in ["12 of 40 files", "1204", "1 m 5 s", "1 of 2000 rows", "output.csv", "1 KB"] {
            XCTAssertTrue(shown.texts.contains(text), text)
        }
    }
    func testInvalidRetainsRawJSON() {
        let raw = "{ broken JSON"
        guard case .invalid(let source) = BlocksResult.decode(Data(raw.utf8)) else { return XCTFail("Invalid JSON") }
        XCTAssertEqual(source, raw)
    }
}
