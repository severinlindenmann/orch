import XCTest
@testable import OrchMobile

/// Team chat step 2 in the app (ORCH-1175): members with who added them, older orch, the Add choice, names of other
/// workspaces in a ticket chat.
final class TeamChatTests: XCTestCase {
    private let finance = "ws_fin0000001", home = "ws_hom0000001", bank = "ws_ban0000001", phone = "ph_own0000001"
    private var names: [String: String] { [finance: "Finance", home: "Home", bank: "Bank"] }

    /// A host copy to the phones as chat groups v2 sends it (members with added_by, joined_at and versions).
    private func copy(_ id: String, seq: Int, text: String, origin: String? = nil, event: [String: Any]? = nil,
                      hostVersion: Int? = 2, update: String? = "note") throws -> PhoneMessage {
        var host: [String: Any] = ["ws": finance, "name": "Finance", "joined_at": "2026-11-08T10:00:00Z"]
        if let hostVersion { host["chat_groups"] = hostVersion; host["orch_version"] = "0.9.5" }
        var body: [String: Any] = [
            "text": text, "by": origin ?? finance, "via": "helper",
            "group": ["id": "grp_t_fin14a", "host": finance, "title": "Pay car tax 2027", "seq": seq, "members": [
                host,
                ["ws": home, "name": "Home", "added_by": "you", "joined_at": "2026-11-08T10:01:00Z", "orch_version": "0.9.5", "chat_groups": 2],
                ["ws": bank, "name": "Bank", "look": ["icon": "wallet", "color": "blue"], "added_by": finance, "joined_at": "2026-11-08T10:05:00Z"],
            ]],
            "origin": ["id": id + "o", "from": origin ?? finance, "at": "2026-11-08T10:06:00Z"],
        ]
        if let update { body["update"] = ["kind": update] }
        if let event { body["group_event"] = event }
        let message: [String: Any] = ["id": id, "from": finance, "to": "phones", "type": "text", "created_at": "2026-11-08T10:06:00Z",
                                      "ticket": "t_fin14a", "key": "FIN-14", "body": body]
        let decoded = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: message))
        return PhoneMessage(message: decoded, workspaceName: "Finance")
    }

    private func group(_ messages: [PhoneMessage]) throws -> PhoneGroup {
        let snapshot = GroupStore.build(messages: messages.reversed(), workspaces: names, ownPhoneId: phone, ownMessageIds: [])
        XCTAssertEqual(snapshot.dropped, [], "the v2 copy passes the phone's group rules")
        return try XCTUnwrap(TeamChatRules.group(in: snapshot.groups, workspace: finance, ticket: "t_fin14a"))
    }

    private func workspace(_ id: String, _ name: String) -> Workspace {
        Workspace(id: id, name: name, description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)
    }

    // MARK: Members and chat info

    func testMembersCarryAddedByJoinedAtAndVersions() throws {
        let g = try group([copy("m_t1", seq: 1, text: "Started")])
        let members = TeamChatRules.members(g, workspace: finance, workspaceName: "Finance")
        XCTAssertEqual(members.map(\.ws), [finance, home, bank], "the ticket's workspace first")
        XCTAssertEqual(members[1].addedBy, "you")
        XCTAssertEqual(members[1].chatGroups, 2)
        XCTAssertEqual(members[2].addedBy, finance)
        XCTAssertNil(members[2].chatGroups)
        XCTAssertEqual(members[2].look?.icon, "wallet")
    }

    func testAddedLineSaysWhoAndWhen() throws {
        let members = TeamChatRules.members(try group([copy("m_t1", seq: 1, text: "x")]), workspace: finance, workspaceName: "Finance")
        XCTAssertEqual(TeamChatRules.addedLine(members[0], host: finance, hostName: "Finance"), "This ticket's workspace")
        XCTAssertEqual(TeamChatRules.addedLine(members[1], host: finance, hostName: "Finance"), "Added by you · 8 Nov")
        XCTAssertEqual(TeamChatRules.addedLine(members[2], host: finance, hostName: "Finance"), "Added by Finance · 8 Nov")
        // A v1 entry without the new fields, and an added_by that is not "you" or the host (never trusted as a name).
        XCTAssertEqual(TeamChatRules.addedLine(GroupMember(ws: home, name: "Home"), host: finance, hostName: "Finance"), "In this chat")
        XCTAssertEqual(TeamChatRules.addedLine(GroupMember(ws: home, name: "Home", addedBy: bank, joinedAt: "2026-11-08T10:01:00Z"),
                                               host: finance, hostName: "Finance"), "Added 8 Nov")
    }

    func testOlderOrchOnlyWhenTheHostSpeaksVersion2() throws {
        let members = TeamChatRules.members(try group([copy("m_t1", seq: 1, text: "x")]), workspace: finance, workspaceName: "Finance")
        XCTAssertFalse(TeamChatRules.isOlder(members[0], members: members, host: finance), "never the ticket's workspace")
        XCTAssertFalse(TeamChatRules.isOlder(members[1], members: members, host: finance))
        XCTAssertTrue(TeamChatRules.isOlder(members[2], members: members, host: finance), "Bank reported no version")
        let v1 = TeamChatRules.members(try group([copy("m_t2", seq: 1, text: "x", hostVersion: nil)]), workspace: finance, workspaceName: "Finance")
        XCTAssertFalse(v1.contains { TeamChatRules.isOlder($0, members: v1, host: finance) }, "a v1 host lists no versions: nobody is marked")
    }

    func testWithoutAGroupOnlyTheTicketsWorkspace() {
        let members = TeamChatRules.members(nil, workspace: finance, workspaceName: "Finance")
        XCTAssertEqual(members.map(\.ws), [finance])
    }

    func testCandidatesAreThePhonesOtherWorkspaces() throws {
        let members = TeamChatRules.members(try group([copy("m_t1", seq: 1, text: "x")]), workspace: finance, workspaceName: "Finance")
        let mine = [workspace(finance, "Finance"), workspace(home, "Home"), workspace("ws_rep0000001", "Reports")]
        XCTAssertEqual(TeamChatRules.candidates(mine, members: members).map(\.id), ["ws_rep0000001"])
        XCTAssertTrue(TeamChatStrip.shows(members: [members[0]], candidates: [mine[2]]))
        XCTAssertFalse(TeamChatStrip.shows(members: [members[0]], candidates: []), "nothing to add and nobody else: no strip")
        XCTAssertEqual(TeamChatRules.pending([home, "ws_rep0000001"], members: members), ["ws_rep0000001"])
    }

    func testStripText() {
        let m = ["Finance", "Home", "Bank", "Sales"].enumerated().map { GroupMember(ws: "ws_x00000000\($0.offset)", name: $0.element) }
        XCTAssertEqual(TeamChatRules.stripText(Array(m.prefix(1))), "Finance")
        XCTAssertEqual(TeamChatRules.stripText(Array(m.prefix(2))), "Finance and Home")
        XCTAssertEqual(TeamChatRules.stripText(Array(m.prefix(3))), "Finance, Home and Bank")
        XCTAssertEqual(TeamChatRules.stripText(m), "Finance, Home and 2 more")
    }

    // MARK: Names in the ticket chat

    func testAMembersQuietCopyShowsInTheTicketChatWithItsWorkspace() throws {
        let talk = try copy("m_talk", seq: 2, text: "Bank here: paid.", origin: bank)
        let event = try copy("m_evt", seq: 3, text: "Finance added Bank", event: ["kind": "member_added", "ws": bank, "name": "Bank", "from_seq": 3])
        let id = ConversationID.topic(workspace: finance, ticket: "t_fin14a")
        let items = ConversationBuilder.items(id, ConversationInputs(messages: [talk, event]))
        XCTAssertEqual(items.map(\.text), ["Bank here: paid."], "member talk shows, the member event stays out of the chat")
        XCTAssertEqual(items.first?.senderWs, bank)
        XCTAssertEqual(items.first?.originId, "m_talko")
        if let item = items.first {
            XCTAssertEqual(ChatNames.caption(item, workspaceName: "Finance", memberName: "Bank"), "Helper · Bank")
        }
        // The ticket's own helper keeps "Finance" (no senderWs).
        let own = try copy("m_own", seq: 4, text: "Paying now.")
        XCTAssertNil(ConversationBuilder.items(id, ConversationInputs(messages: [own])).first?.senderWs)
    }

    func testAChatLineWithTheSameOriginIdShowsOnce() throws {
        let talk = try copy("m_talk", seq: 2, text: "Bank here: paid.", origin: bank)
        var t = Ticket(id: "\(finance)|t_fin14a", workspace: finance, workspaceName: "Finance", ticket: "t_fin14a", title: "Tax", text: "",
                       status: .working, kind: "working", at: "2026-11-08T10:06:00Z", question: nil)
        t.view = TicketSnapshot(historyTail: [.init(at: "2026-11-08T10:06:00Z", by: "Bank", role: "agent", text: "Bank here: paid.", chat: true, messageId: "m_talko")])
        let items = ConversationBuilder.items(.topic(workspace: finance, ticket: "t_fin14a"), ConversationInputs(messages: [talk], tickets: [t]))
        XCTAssertEqual(items.count, 1)
    }

    // MARK: The Add choice on the wire

    func testTeamChoiceNeedsTextTicketAndAValidForm() throws {
        let ok = SendRequest(to: finance, clientId: "6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e1175", text: "Add Home to this chat", ticket: "t_fin14a",
                             team: TeamChoice(add: home))
        XCTAssertNoThrow(try ok.validate())
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(ok)) as? [String: Any])
        XCTAssertEqual((json["team"] as? [String: Any])?["add"] as? String, home)
        var noTicket = ok; noTicket.ticket = nil
        XCTAssertThrowsError(try noTicket.validate()) { XCTAssertEqual($0 as? SendRequest.Problem, .badTeam) }
        var noText = ok; noText.text = nil; noText.location = LocationShare(lat: 47, lon: 8)
        XCTAssertThrowsError(try noText.validate())
        for bad in [TeamChoice(), TeamChoice(add: "ph_own0000001"), TeamChoice(mentions: []), TeamChoice(mentions: [bank, bank])] {
            var r = ok; r.team = bad
            XCTAssertThrowsError(try r.validate(), "\(bad)")
        }
    }

    func testReceiptSaysWhetherTheRelayKeptTheChoice() throws {
        let kept = try JSONCoding.decoder.decode(SendReceipt.self, from: Data(#"{"id":"m_a1b2c3d4e5f6a7b8","client_id":null,"team":true}"#.utf8))
        XCTAssertEqual(kept.team, true)
        let old = try JSONCoding.decoder.decode(SendReceipt.self, from: Data(#"{"id":"m_a1b2c3d4e5f6a7b8"}"#.utf8))
        XCTAssertNil(old.team, "an older relay answers without it")
    }

    @MainActor
    func testMockAddsTheWorkspaceAndSaysKept() async throws {
        let relay = MockRelay(latency: .zero)
        let r = SendRequest(to: MockRelay.pilatus, clientId: "6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e1176", text: "Add Reports to this chat",
                            ticket: "t_7k3f9q", team: TeamChoice(add: MockRelay.reports))
        let receipt = try await relay.send(r)
        XCTAssertEqual(receipt.team, true)
    }
}
