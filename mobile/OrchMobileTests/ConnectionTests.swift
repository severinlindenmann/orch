import XCTest
@testable import OrchMobile

@MainActor
final class ConnectionTests: XCTestCase {
    func testConnectionComesFromTransportOnly() {
        XCTAssertEqual(AppModel.connection(transportDown: false, hasLoaded: false), .checking)
        XCTAssertEqual(AppModel.connection(transportDown: false, hasLoaded: true), .ok)
        XCTAssertEqual(AppModel.connection(transportDown: true, hasLoaded: true), .unreachable)
        XCTAssertEqual(AppModel.connection(transportDown: true, hasLoaded: false), .unreachable)
    }

    func testOnlyNetworkFailuresAreTransportErrors() {
        XCTAssertTrue(AppModel.isTransportError(URLError(.notConnectedToInternet)))
        XCTAssertTrue(AppModel.isTransportError(RelayError.network("down")))
        XCTAssertFalse(AppModel.isTransportError(RelayError.api(status: 409, code: "taken", message: "Already answered")))
        XCTAssertFalse(AppModel.isTransportError(RelayError.badLink))
    }

    func testNotificationsRowValue() {
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(identifier: "UTC")!
        let now = MuteRules.date("2026-11-12T10:00:00Z")!
        XCTAssertEqual(MuteRules.notificationsValue(nil, now: now, calendar: calendar), "On")
        XCTAssertEqual(MuteRules.notificationsValue("2026-11-12T09:00:00Z", now: now, calendar: calendar), "On")
        XCTAssertEqual(MuteRules.notificationsValue("forever", now: now, calendar: calendar), "Muted")
        XCTAssertEqual(MuteRules.notificationsValue("2026-11-12T11:00:00Z", now: now, calendar: calendar), "Muted until 11:00")
        XCTAssertEqual(MuteRules.notificationsValue("2026-11-13T08:00:00Z", now: now, calendar: calendar), "Muted until tomorrow 08:00")
    }
}
