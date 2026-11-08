import XCTest
@testable import OrchMobile

@MainActor
final class FreshInstallTests: XCTestCase {
    private let creds = Credentials(relay: URL(string: "https://relay.severin.io")!, phoneId: "ph_fresh0001", token: "orn_x", phoneName: "P")
    private func defaults() -> UserDefaults {
        let name = "fresh-install-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!; d.removePersistentDomain(forName: name); return d
    }
    private func model(_ d: UserDefaults) -> AppModel {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("fresh-\(UUID().uuidString)")
        return AppModel(useMock: true, voiceMode: .scripted, outboxDirectory: dir, speechCache: dir.appendingPathComponent("sp"), systemAudioControls: false, defaults: d)
    }
    override func tearDown() { Keychain.delete() }

    func testNoMarkerClearsStaleKeychainAndShowsOnboarding() {
        Keychain.save(creds)
        let d = defaults()
        d.set(creds.phoneId, forKey: "pairedPhoneId")
        let m = model(d)
        XCTAssertEqual(m.phase, .onboarding)
        XCTAssertNil(Keychain.load())
        XCTAssertNil(m.message)
        XCTAssertNil(d.object(forKey: "pairedPhoneId"))
        XCTAssertTrue(d.bool(forKey: AppModel.installedMarkerKey))
    }

    func testMissingKeychainShowsPairAgainOnce() {
        Keychain.delete()
        let d = defaults()
        d.set(true, forKey: AppModel.installedMarkerKey)
        d.set(creds.phoneId, forKey: "pairedPhoneId")

        let m = model(d)

        XCTAssertEqual(m.message, AppModel.pairAgainMessage)
        XCTAssertEqual(m.phase, .onboarding)
        XCTAssertNil(d.object(forKey: "pairedPhoneId"))
        XCTAssertNil(model(d).message)
    }

    func testMissingKeychainWithoutPreviousPairingShowsNoMessage() {
        Keychain.delete()
        let d = defaults()
        d.set(true, forKey: AppModel.installedMarkerKey)

        let m = model(d)

        XCTAssertNil(m.message)
        XCTAssertEqual(m.phase, .onboarding)
    }

    func testPairingRemembersPhoneAndSignOutClearsIt() async throws {
        Keychain.delete()
        let d = defaults()
        let m = model(d)
        m.openSampleInvite()
        await m.connect(phoneName: "P")

        let paired = try XCTUnwrap(m.credentials)
        XCTAssertEqual(m.phase, .notifyStep)
        XCTAssertEqual(d.string(forKey: "pairedPhoneId"), paired.phoneId)

        await m.signOut()

        XCTAssertNil(d.object(forKey: "pairedPhoneId"))
        XCTAssertEqual(m.phase, .onboarding)
    }

    func testMarkerKeepsPairingAndRevokedKeepsSignedOutMessage() {
        let d = defaults(); d.set(true, forKey: AppModel.installedMarkerKey)
        Keychain.save(creds)
        XCTAssertEqual(model(d).phase, .ready)
        XCTAssertNotNil(Keychain.load())
        XCTAssertEqual(RelayError.unauthorized.localizedDescription, "This phone was signed out. Open the invitation you were sent to connect again.")
    }
}
