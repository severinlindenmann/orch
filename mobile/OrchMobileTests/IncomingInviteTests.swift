import XCTest
@testable import OrchMobile

/// ORCH-2127: an invitation opened on a phone that is already paired goes to the Add workspace confirmation and its code
/// only to the server this phone is paired with. Real client on stub transport, so every request is seen.
@MainActor
final class IncomingInviteTests: XCTestCase {
    private let relay = URL(string: "https://relay.test")!
    private let redeemPath = "/v1/phone/invitations/redeem"
    private var dir: URL!
    private var defaults: UserDefaults!

    override func setUp() async throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("incoming-\(UUID().uuidString)")
        let name = "incoming-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: name)!; defaults.removePersistentDomain(forName: name)
        defaults.set(true, forKey: AppModel.installedMarkerKey)
        StubProtocol.handler = { [redeemPath] req in
            if req.url?.path == redeemPath, let ex = try? Example.find("POST", redeemPath, status: 200) { return (200, ex.responseData) }
            return (500, Data())
        }
    }
    override func tearDown() async throws {
        Keychain.delete(); StubProtocol.handler = nil
        try? FileManager.default.removeItem(at: dir)
    }

    private func pairedModel() -> AppModel {
        Keychain.save(Credentials(relay: relay, phoneId: "ph_iphone0001", token: "orn_x", phoneName: "P"))
        let m = AppModel(useMock: false, session: StubProtocol.session(), voiceMode: .scripted, outboxDirectory: dir,
                         speechCache: dir.appendingPathComponent("sp"), systemAudioControls: false, defaults: defaults)
        XCTAssertEqual(m.phase, .ready)
        return m
    }
    private func link(_ server: String, _ code: String = "pc_Rd3Em9Kx2Lp4Qw6Er8Ty1U") -> String {
        "orch://pair?relay=\(server.addingPercentEncoding(withAllowedCharacters: .alphanumerics)!)&code=\(code)"
    }
    private var redeemRequests: [URLRequest] { StubProtocol.seen.filter { $0.url?.path == redeemPath } }

    func testSameOriginComparesSchemeHostAndPort() {
        XCTAssertTrue(IncomingInvite.sameOrigin(relay, URL(string: "https://RELAY.test:443/")!))
        XCTAssertFalse(IncomingInvite.sameOrigin(relay, URL(string: "https://relay.test:8443")!))
        XCTAssertFalse(IncomingInvite.sameOrigin(relay, URL(string: "http://relay.test")!))
        XCTAssertFalse(IncomingInvite.sameOrigin(relay, URL(string: "https://relay.test.evil.example")!))
    }

    func testMatchingInvitationIsConfirmedThenRedeemedOnceOnThePairedServer() async throws {
        let m = pairedModel()
        let before = m.credentials
        m.openInvite(link("https://relay.test"))
        let incoming = try XCTUnwrap(m.incomingInvite, "held for the Add workspace confirmation")
        XCTAssertTrue(redeemRequests.isEmpty, "nothing is sent before Add")
        XCTAssertEqual(m.inviteState, .none); XCTAssertNil(m.invite); XCTAssertEqual(m.phase, .ready)
        XCTAssertEqual(m.takeIncomingInvite(), incoming); XCTAssertNil(m.incomingInvite)
        XCTAssertTrue(m.isForPairedServer(incoming))

        async let first = m.redeemInvitation(incoming.link)
        async let second = m.redeemInvitation(incoming.link)
        let (a, b) = await (first, second)
        XCTAssertEqual((a + b).map(\.id), ["ws_reports001"], "a double tap adds once")
        XCTAssertEqual(redeemRequests.count, 1)
        XCTAssertEqual(redeemRequests[0].url?.host, "relay.test")
        XCTAssertEqual(m.credentials, before, "the pairing stays")
    }

    func testMismatchedInvitationIsNeverSent() async throws {
        let m = pairedModel()
        let before = m.credentials
        for server in ["https://other.example", "https://relay.test:8443"] {
            m.openInvite(link(server))
            let incoming = try XCTUnwrap(m.takeIncomingInvite())
            XCTAssertFalse(m.isForPairedServer(incoming))
            let added = await m.redeemInvitation(incoming.link)
            XCTAssertTrue(added.isEmpty)
            XCTAssertEqual(m.message, IncomingInvite.otherServer)
        }
        XCTAssertTrue(StubProtocol.seen.isEmpty, "no request at all, to either server")
        XCTAssertEqual(m.credentials, before); XCTAssertEqual(m.phase, .ready)
    }

    func testCanceledInvitationLeavesThePairingAsItIs() {
        let m = pairedModel()
        let before = m.credentials
        m.openInvite(link("https://relay.test"))
        _ = m.takeIncomingInvite()   // the sheet took it; closing it without Add drops it
        XCTAssertNil(m.incomingInvite)
        XCTAssertTrue(StubProtocol.seen.isEmpty)
        XCTAssertEqual(m.credentials, before); XCTAssertEqual(m.phase, .ready); XCTAssertEqual(m.inviteState, .none)
        m.openInvite("orch://pair?relay=nope")
        XCTAssertNil(m.incomingInvite); XCTAssertNotNil(m.message); XCTAssertEqual(m.credentials, before)
    }

    func testFirstTimeSetupStillOpensTheConnectStep() {
        Keychain.delete()
        let m = AppModel(useMock: false, session: StubProtocol.session(), voiceMode: .scripted, outboxDirectory: dir,
                         speechCache: dir.appendingPathComponent("sp"), systemAudioControls: false, defaults: defaults)
        m.openInvite(link("https://relay.test"))
        XCTAssertEqual(m.inviteState, .found(host: "relay.test"))
        XCTAssertNil(m.incomingInvite)
        XCTAssertTrue(StubProtocol.seen.isEmpty)
    }
}
