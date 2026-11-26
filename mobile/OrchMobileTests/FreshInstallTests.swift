import XCTest
import Security
@testable import OrchMobile

/// Credentials in memory: replays a failed read or a failed save without touching this machine's Keychain.
final class FakeCredentialStore: CredentialStore {
    var stored: Credentials?
    /// Answers for the next reads, in order; then `stored` (or missing).
    var reads: [CredentialRead] = []
    var saveWorks = true
    private(set) var deletes = 0
    init(_ stored: Credentials? = nil) { self.stored = stored }
    func read() -> CredentialRead {
        if !reads.isEmpty { return reads.removeFirst() }
        return stored.map { .found($0) } ?? .missing
    }
    func save(_ c: Credentials) -> Bool { if saveWorks { stored = c }; return saveWorks }
    func delete() { stored = nil; deletes += 1 }
}

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

    // MARK: A failed credential read or save (ORCH-2124)

    private let mockPhone = Credentials(relay: URL(string: "https://relay.test")!, phoneId: "ph_iphone0001", token: "orn_t", phoneName: "P")
    private func installed() -> UserDefaults {
        let d = defaults(); d.set(true, forKey: AppModel.installedMarkerKey); d.set(mockPhone.phoneId, forKey: "pairedPhoneId"); return d
    }
    private func outboxDir() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("cred-\(UUID().uuidString)").appendingPathComponent("outbox")
    }
    private func model(_ d: UserDefaults, _ dir: URL, _ store: FakeCredentialStore) -> AppModel {
        AppModel(useMock: true, voiceMode: .scripted, outboxDirectory: dir, speechCache: dir.appendingPathComponent("sp"),
                 systemAudioControls: false, defaults: d, credentialStore: store)
    }
    /// A paired phone with loaded rows on disk and one message waiting in the queue.
    private func pairedWithQueue(_ d: UserDefaults, _ dir: URL, _ store: FakeCredentialStore) async throws -> (AppModel, OutboxItem) {
        let m = model(d, dir, store)
        await m.refresh()
        XCTAssertFalse(m.workspaces.isEmpty)
        let item = try m.outbox.enqueue(MessageDraft(text: "kept while locked"), to: .general(workspace: m.workspaces[0].id))
        m.persistForBackground()
        LocalSnapshotStore.flush(at: LocalSnapshotStore.url(besideOutbox: dir)); Outbox.flushAllWrites()
        return (m, item)
    }

    func testUnreadableCredentialsKeepQueueAndRowsUntilTheNextGoodRead() async throws {
        let d = installed(), dir = outboxDir(), store = FakeCredentialStore(mockPhone)
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        let (warm, item) = try await pairedWithQueue(d, dir, store)

        store.reads = [.unavailable(errSecInteractionNotAllowed), .unavailable(errSecInteractionNotAllowed)]
        let cold = model(d, dir, store)

        XCTAssertEqual(cold.phase, .ready)
        XCTAssertNil(cold.credentials)
        XCTAssertEqual(cold.message, AppModel.credentialsUnavailableMessage)
        XCTAssertEqual(cold.outbox.items.map(\.clientId), [item.clientId])
        XCTAssertEqual(cold.workspaces, warm.workspaces)
        XCTAssertNotNil(LocalSnapshotStore.load(from: LocalSnapshotStore.url(besideOutbox: dir), phoneId: mockPhone.phoneId))
        XCTAssertEqual(store.deletes, 0)

        cold.reloadCredentialsIfNeeded()   // still locked: nothing changes
        XCTAssertNil(cold.credentials); XCTAssertEqual(cold.outbox.items.count, 1)

        cold.reloadCredentialsIfNeeded()   // unlocked: the same pairing, queue and rows
        XCTAssertEqual(cold.credentials, mockPhone)
        XCTAssertFalse(cold.credentialsUnavailable)
        XCTAssertNil(cold.message)
        XCTAssertEqual(cold.outbox.items.map(\.clientId), [item.clientId])
        XCTAssertEqual(cold.workspaces, warm.workspaces)
        XCTAssertEqual(d.string(forKey: "pairedPhoneId"), mockPhone.phoneId)
    }

    func testUnreadableCredentialsOnAnUnmarkedInstallDeleteNothing() {
        let d = defaults(), dir = outboxDir(), store = FakeCredentialStore(mockPhone)
        store.reads = [.unavailable(errSecInteractionNotAllowed)]
        let m = model(d, dir, store)
        XCTAssertEqual(store.deletes, 0, "a failed read is no proof of a fresh install")
        XCTAssertFalse(d.bool(forKey: AppModel.installedMarkerKey))
        XCTAssertEqual(m.phase, .onboarding)
        XCTAssertEqual(m.message, AppModel.credentialsUnavailableMessage)
    }

    func testMissingCredentialsStillClearQueueAndRows() async throws {
        let d = installed(), dir = outboxDir(), store = FakeCredentialStore(mockPhone)
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        _ = try await pairedWithQueue(d, dir, store)

        store.stored = nil
        let cold = model(d, dir, store)

        XCTAssertEqual(cold.phase, .onboarding)
        XCTAssertEqual(cold.message, AppModel.pairAgainMessage)
        XCTAssertTrue(cold.outbox.items.isEmpty)
        XCTAssertNil(LocalSnapshotStore.load(from: LocalSnapshotStore.url(besideOutbox: dir), phoneId: mockPhone.phoneId))
    }

    func testCredentialsGoneAfterAnUnreadableLaunchSignOutLikeAtLaunch() async throws {
        let d = installed(), dir = outboxDir(), store = FakeCredentialStore(mockPhone)
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        _ = try await pairedWithQueue(d, dir, store)

        store.reads = [.unavailable(errSecInteractionNotAllowed)]
        let cold = model(d, dir, store)
        store.stored = nil
        cold.reloadCredentialsIfNeeded()

        XCTAssertEqual(cold.phase, .onboarding)
        XCTAssertEqual(cold.message, AppModel.pairAgainMessage)
        XCTAssertTrue(cold.outbox.items.isEmpty)
    }

    func testFailedSaveDoesNotFinishPairing() async {
        let d = defaults(); d.set(true, forKey: AppModel.installedMarkerKey)
        let dir = outboxDir(), store = FakeCredentialStore()
        store.saveWorks = false
        let m = model(d, dir, store)
        m.openSampleInvite()

        await m.connect(phoneName: "P")

        XCTAssertEqual(m.phase, .onboarding)
        XCTAssertNil(m.credentials)
        XCTAssertNil(store.stored)
        XCTAssertNil(d.object(forKey: "pairedPhoneId"))
        XCTAssertTrue(m.inviteNeedsReplacement)
        XCTAssertEqual(m.message, AppModel.credentialsNotSavedMessage)
    }

    func testTokenSaveReplacesInPlaceAndStaysOnThisDevice() {
        Keychain.delete()
        XCTAssertTrue(Keychain.save(creds))
        let next = Credentials(relay: creds.relay, phoneId: creds.phoneId, token: "orn_y", phoneName: "P")
        XCTAssertTrue(Keychain.save(next))
        XCTAssertEqual(Keychain.load(), next)
        XCTAssertEqual(Keychain.accessibility(), kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String, "never in a backup or iCloud Keychain")
    }

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
