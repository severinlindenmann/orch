import XCTest
@testable import OrchMobile

/// Tool warnings on the phone (contracts/tool-alert.md, vectors/tool-alert-v1.json `valid` and `phone`).
final class ToolAlertTests: XCTestCase {
    private func vector() throws -> [String: Any] {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/tool-alert-v1.json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func phoneMessage(_ item: [String: Any]) throws -> PhoneMessage {
        try JSONCoding.decoder.decode(PhoneMessage.self, from: JSONSerialization.data(withJSONObject: item))
    }

    func testValidWarningsDecodeAsSilentRows() throws {
        let entries = try XCTUnwrap(vector()["valid"] as? [[String: Any]])
        XCTAssertFalse(entries.isEmpty)
        for entry in entries {
            let message = try XCTUnwrap(entry["message"] as? [String: Any])
            let raw = try XCTUnwrap((message["body"] as? [String: Any])?["tool_alert"] as? [String: Any])
            let decoded = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: message))
            let alert = try XCTUnwrap(decoded.body.toolAlert, "\(entry["name"] ?? "")")
            XCTAssertEqual(alert.name, raw["name"] as? String)
            XCTAssertEqual(alert.state, raw["state"] as? String)
            XCTAssertEqual(alert.stops, raw["stops"] as? [String])
            XCTAssertEqual(alert.noNewWork, raw["no_new_work"] as? Bool)
            XCTAssertTrue(decoded.body.isSilentResult)
        }
    }

    func testPhoneCases() throws {
        let cases = try XCTUnwrap(vector()["phone"] as? [[String: Any]])
        XCTAssertFalse(cases.isEmpty)
        for c in cases {
            let name = c["name"] as? String ?? ""
            let messages = try XCTUnwrap(c["messages"] as? [[String: Any]]).map(phoneMessage)
            let want = try XCTUnwrap(c["rows"] as? [[String: Any]])
            let got = ToolAlertRules.rows(messages, workspaceId: "ws_pilatus001")
            XCTAssertEqual(got.map(\.name), want.map { $0["name"] as? String ?? "" }, name)
            XCTAssertEqual(got.map(\.tone), want.map { $0["tone"] as? String ?? "" }, name)
            XCTAssertEqual(got.map(\.text), want.map { $0["text"] as? String ?? "" }, name)
            XCTAssertEqual(messages.filter { !$0.message.body.isSilentResult }.count, c["bubbles"] as? Int, name)
        }
    }

    func testOtherWorkspaceAndPhoneTextsMakeNoRow() throws {
        let cases = try XCTUnwrap(vector()["phone"] as? [[String: Any]])
        let first = try XCTUnwrap(cases.first?["messages"] as? [[String: Any]]).map(phoneMessage)
        XCTAssertEqual(ToolAlertRules.rows(first, workspaceId: "ws_other00001"), [])
    }
}
