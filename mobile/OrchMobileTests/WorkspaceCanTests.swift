import XCTest
@testable import OrchMobile

/// contracts/vectors/phone-can-v1.json replayed (R9.4): GET /v1/phone/workspaces with and without `can`. Every case
/// still lists the workspace; a `can` the relay must never send is read as unknown (nil), an unknown extra key is ignored.
final class WorkspaceCanTests: XCTestCase {
    func testPhoneCanVector() throws {
        struct Vectors: Decodable { let workspaces: [Case] }
        struct Case: Decodable { let name: String; let ok: Bool; let response: Page }
        struct Page: Decodable { let items: [Workspace] }
        let all = WorkspaceCan(chat: true, tasks: true, files: true)
        let expected: [String: WorkspaceCan?] = [
            "paired-phone": all,
            "older-relay": nil,
            "can-missing-key": nil,
            "can-extra-key": all,
            "can-non-bool": nil,
            "can-null": nil,
        ]
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/phone-can-v1.json"))
        let vectors = try JSONCoding.decoder.decode(Vectors.self, from: data)
        XCTAssertEqual(Set(vectors.workspaces.map(\.name)), Set(expected.keys))
        for c in vectors.workspaces {
            XCTAssertEqual(c.response.items.count, 1, c.name)
            XCTAssertEqual(c.response.items.first?.id, "ws_pilatus001", c.name)
            XCTAssertEqual(c.response.items.first?.can, expected[c.name] ?? nil, c.name)
        }
    }
}
