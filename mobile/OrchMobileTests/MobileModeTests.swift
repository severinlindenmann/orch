import XCTest
@testable import OrchMobile

final class MobileModeTests: XCTestCase {
    private func ws(on: Bool, machine: String? = "Acme PC", lastSeen: String?, muted: String? = nil) -> Workspace {
        Workspace(id: "ws_a", name: "Acme", description: nil, tags: [], online: true, lastSeen: lastSeen, openQuestions: 0,
                  mutedUntil: muted, mobileMode: MobileMode(on: on, since: nil, endsAt: nil, machine: machine))
    }
    private let now = ISO8601DateFormatter().date(from: "2026-11-07T14:40:00Z")!
    private var cal: Calendar { var c = Calendar(identifier: .gregorian); c.timeZone = TimeZone(identifier: "UTC")!; return c }

    func testOffShowsNothing() {
        XCTAssertNil(MobileModeBannerState.of(ws(on: false, lastSeen: "2026-11-07T14:39:00Z"), now: now, calendar: cal))
    }
    func testOnlineShowsTurnOff() {
        let s = MobileModeBannerState.of(ws(on: true, lastSeen: "2026-11-07T14:39:00Z"), now: now, calendar: cal)
        XCTAssertEqual(s?.text, "Acme PC · Mobile mode on")
        XCTAssertEqual(s?.canTurnOff, true)
    }
    func testSilentComputerSaysSinceWhen() {
        let s = MobileModeBannerState.of(ws(on: true, lastSeen: "2026-11-07T14:31:00Z"), now: now, calendar: cal)
        XCTAssertEqual(s?.text, "Acme PC · Can't reach since 14:31")
        XCTAssertEqual(s?.canTurnOff, false)
    }
    func testMutedPhoneSaysMutedBut() {
        let s = MobileModeBannerState.of(ws(on: true, lastSeen: "2026-11-07T14:39:00Z", muted: "forever"), now: now, calendar: cal)
        XCTAssertEqual(s?.text, "Acme PC · Mobile mode muted")
    }
    func testMissingMachineFallsBackToWorkspaceName() {
        let s = MobileModeBannerState.of(ws(on: true, machine: nil, lastSeen: "2026-11-07T14:39:00Z"), now: now, calendar: cal)
        XCTAssertEqual(s?.text, "Acme · Mobile mode on")
    }
    func testDecodesTheRelayShape() throws {
        let json = #"{"id":"ws_a","name":"A","description":"","tags":[],"online":true,"last_seen":null,"open_questions":0,"muted_until":null,"mobile_mode":{"on":true,"since":"2026-11-07T14:02:00Z","ends_at":"2026-11-08T02:02:00Z","machine":"Acme PC"}}"#
        let w = try JSONCoding.decoder.decode(Workspace.self, from: Data(json.utf8))
        XCTAssertEqual(w.mobileMode?.machine, "Acme PC")
        XCTAssertEqual(w.mobileMode?.on, true)
    }

    func testOnBannerIsTintedAndOthersDiffer() {
        XCTAssertNotEqual(MobileModeBannerState.on(pc: "A").background, MobileModeBannerState.muted(pc: "A").background)
        XCTAssertNotEqual(MobileModeBannerState.on(pc: "A").background, MobileModeBannerState.unreachable(pc: "A", since: nil).background)
    }
}
