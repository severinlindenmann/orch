import XCTest
@testable import OrchMobile

final class ContactListTests: XCTestCase {
    func testChips() {
        XCTAssertEqual(ContactList.chips(nil), [])
        XCTAssertEqual(ContactList.chips(WorkspaceCan(chat: true, tasks: true, files: true)), [])
        XCTAssertEqual(ContactList.chips(WorkspaceCan(chat: true, tasks: false, files: false)), ["Chat"])
        XCTAssertEqual(ContactList.chips(WorkspaceCan(chat: false, tasks: false, files: false)), ["No access"])
        XCTAssertEqual(ContactList.chips(WorkspaceCan(chat: false, tasks: true, files: true)), ["Give tasks", "Files"])
    }

    func testWorkspaceCanDecoding() throws {
        let base = #"""
        "id":"ws_reports001","name":"Reports","tags":[],"online":true,
        "last_seen":"2026-11-04T10:50:00Z","open_questions":2,
        "muted_until":"forever","mobile_mode":{"on":true,"ends_at":"2026-11-05T10:50:00Z"},
        "icon":"wallet","color":"amber"
        """#
        let valid = "{" + base + #", "can":{"chat":true,"tasks":false,"files":false}}"#
        let legacy = "{" + base + "}"
        let workspace = try JSONCoding.decoder.decode(Workspace.self, from: Data(valid.utf8))
        XCTAssertEqual(workspace.can, WorkspaceCan(chat: true, tasks: false, files: false))
        XCTAssertEqual(workspace.lastSeen, "2026-11-04T10:50:00Z")
        XCTAssertEqual(workspace.openQuestions, 2)
        XCTAssertEqual(workspace.mutedUntil, "forever")
        XCTAssertEqual(workspace.mobileMode?.endsAt, "2026-11-05T10:50:00Z")
        XCTAssertEqual(workspace.icon, "wallet")
        XCTAssertEqual(workspace.color, "amber")
        XCTAssertNil(try JSONCoding.decoder.decode(Workspace.self, from: Data(legacy.utf8)).can)
        XCTAssertEqual(try JSONCoding.decoder.decode(Workspace.self, from: JSONCoding.encoder.encode(workspace)), workspace)

        for malformed in ["null", "false", "[]", #""bad""#, "{}",
                          #"{"chat":true,"tasks":false}"#,
                          #"{"chat":"true","tasks":false,"files":false}"#,
                          #"{"chat":true,"tasks":null,"files":false}"#] {
            let item = "{" + base + ",\"can\":" + malformed + "}"
            let list = #"{"items":["# + item + "," + valid + "," + legacy + "]}"
            let decoded = try JSONCoding.decoder.decode(ListResponse<Workspace>.self, from: Data(list.utf8))
            XCTAssertEqual(decoded.items.count, 3)
            XCTAssertNil(decoded.items[0].can, malformed)
            XCTAssertEqual(decoded.items[1].can, workspace.can)
            XCTAssertNil(decoded.items[2].can)
        }
    }

    private func workspace(_ id: String, _ name: String) -> Workspace {
        Workspace(id: id, name: name, description: nil, tags: [], online: false, lastSeen: nil, openQuestions: 0)
    }

    func testFilterAndSort() {
        let rows = [workspace("reports", "Reports"), workspace("pilatus", "Pílatus"), workspace("home", "home")]
        XCTAssertEqual(ContactList.rows(rows, query: "").map(\.id), ["home", "pilatus", "reports"])
        XCTAssertEqual(ContactList.rows(rows, query: " PIL ").map(\.id), ["pilatus"])
        XCTAssertEqual(ContactList.rows(rows, query: "píl").map(\.id), ["pilatus"])
        XCTAssertTrue(ContactList.rows(rows, query: "missing").isEmpty)
        XCTAssertTrue(ContactList.rows([], query: "").isEmpty)
        XCTAssertEqual(ContactList.rows(rows, query: " \n ").map(\.id), ["home", "pilatus", "reports"])
    }

    func testDisplayNamesAndStableTies() {
        let rows = [workspace("b", "Zulu"), workspace("a", "Alpha")]
        let names = ["b": "Écho", "a": "echo"]
        XCTAssertEqual(ContactList.rows(rows, query: "ECHO", names: names).map(\.id), ["a", "b"])
        XCTAssertTrue(ContactList.rows(rows, query: "Zulu", names: names).isEmpty)
    }
}
