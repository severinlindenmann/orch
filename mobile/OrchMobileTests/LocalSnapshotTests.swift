import XCTest
@testable import OrchMobile

@MainActor
final class LocalSnapshotTests: XCTestCase {
    private let phone = "ph_iphone0001"   // the id the in-process mock hands out
    private var dir: URL!
    private var defaults: UserDefaults!

    override func setUp() {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("snap-\(UUID().uuidString)").appendingPathComponent("outbox")
        let name = "snap-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: name)!; defaults.removePersistentDomain(forName: name)
        defaults.set(true, forKey: AppModel.installedMarkerKey)
        Keychain.save(Credentials(relay: URL(string: "https://relay.test")!, phoneId: phone, token: "orn_snap", phoneName: "Test"))
    }
    override func tearDown() {
        Keychain.delete(); StubProtocol.failNext = 0
        try? FileManager.default.removeItem(at: dir.deletingLastPathComponent())
    }

    private var snapshotURL: URL { LocalSnapshotStore.url(besideOutbox: dir) }
    private func model(mock: Bool = true) -> AppModel {
        AppModel(useMock: mock, session: StubProtocol.session(), voiceMode: .scripted, outboxDirectory: dir,
                 speechCache: dir.appendingPathComponent("sp"), systemAudioControls: false, defaults: defaults)
    }
    /// A model that loaded from the mock relay and wrote its snapshot.
    private func filledModel() async -> AppModel {
        let m = model()
        await m.refresh()
        XCTAssertFalse(m.workspaces.isEmpty)
        m.persistSnapshotNow()
        LocalSnapshotStore.flush(at: snapshotURL)
        return m
    }

    func testRoundTrip() async throws {
        let m = await filledModel()
        let s = try XCTUnwrap(LocalSnapshotStore.load(from: snapshotURL, phoneId: phone))
        XCTAssertEqual(s.workspaces, m.workspaces)
        XCTAssertEqual(s.questions, m.questions)
        XCTAssertEqual(s.messages, m.messages)
        XCTAssertEqual(s.updates, m.updates)
        XCTAssertEqual(s.version, LocalSnapshot.currentVersion)
    }

    func testColdModelShowsRowsBeforeAnyNetworkCall() async {
        let filled = await filledModel()
        StubProtocol.seen = []
        let cold = model(mock: false)   // real client against a stub that is never called
        XCTAssertEqual(cold.workspaces, filled.workspaces)
        XCTAssertEqual(cold.messages, filled.messages)
        XCTAssertFalse(cold.groups.groups.isEmpty && !filled.groups.groups.isEmpty)
        XCTAssertFalse(cold.hasLoaded, "the connection may still say Checking")
        XCTAssertTrue(cold.restoredFromSnapshot)
        XCTAssertFalse(cold.showsLoadingPlaceholder, "rows replace the loading skeleton")
        XCTAssertTrue(StubProtocol.seen.isEmpty)
        XCTAssertFalse(cold.workspaceSummaries.isEmpty)
    }

    func testFailingRefreshKeepsTheRows() async {
        let filled = await filledModel()
        let cold = model(mock: false)
        cold.retryDelay = .milliseconds(10)
        StubProtocol.failNext = 100
        await cold.refresh()
        XCTAssertNotNil(cold.message)
        XCTAssertEqual(cold.workspaces, filled.workspaces)
        XCTAssertEqual(cold.messages, filled.messages)
        XCTAssertFalse(cold.showsLoadingPlaceholder)
    }

    func testSuccessfulRefreshMergesMessagesAndKeepsOlderOnes() async {
        let filled = await filledModel()
        let cold = model(mock: false)
        StubProtocol.handler = { _ in (200, Data(#"{"items":[]}"#.utf8)) }
        let before = cold.messages.count
        XCTAssertGreaterThan(before, 0)
        await cold.refresh()
        XCTAssertEqual(cold.messages.count, before, "an empty page never removes known messages")
        XCTAssertEqual(cold.messages, filled.messages)
    }

    func testSignOutDeletesTheFile() async {
        let m = await filledModel()
        XCTAssertTrue(FileManager.default.fileExists(atPath: snapshotURL.path))
        await m.signOut()
        LocalSnapshotStore.flush(at: snapshotURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: snapshotURL.path))
    }

    func testAnotherPhonesSnapshotIsIgnoredAndDeleted() async {
        _ = await filledModel()
        Keychain.save(Credentials(relay: URL(string: "https://relay.test")!, phoneId: "ph_other00002", token: "orn_x", phoneName: "Other"))
        let m = model(mock: false)
        XCTAssertTrue(m.workspaces.isEmpty)
        XCTAssertTrue(m.messages.isEmpty)
        XCTAssertFalse(m.restoredFromSnapshot)
        LocalSnapshotStore.flush(at: snapshotURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: snapshotURL.path))
    }

    func testCorruptFileIsIgnoredAndDeleted() throws {
        try FileManager.default.createDirectory(at: dir.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("not json".utf8).write(to: snapshotURL)
        let m = model(mock: false)
        XCTAssertTrue(m.workspaces.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: snapshotURL.path))
    }

    func testCursorSurvivesWhenTheListWasNotCut() async throws {
        let m = await filledModel()
        var s = try XCTUnwrap(LocalSnapshotStore.load(from: snapshotURL, phoneId: phone))
        s.messagesNext = "cursor"
        LocalSnapshotStore.save(s, to: snapshotURL)
        LocalSnapshotStore.flush(at: snapshotURL)
        let cold = model(mock: false)
        XCTAssertEqual(cold.messagesNext, "cursor", "an uncut list keeps its cursor")
        XCTAssertLessThanOrEqual(m.messages.count, LocalSnapshot.messageLimit)
    }

    func testSnapshotFileIsProtectedAndSitsBesideTheOutbox() async {
        _ = await filledModel()
        XCTAssertEqual(snapshotURL.deletingLastPathComponent(), dir.deletingLastPathComponent())
        XCTAssertNotEqual(snapshotURL.deletingLastPathComponent(), dir)
    }
}
