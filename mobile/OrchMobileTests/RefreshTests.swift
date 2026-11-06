import XCTest
@testable import OrchMobile

@MainActor
final class RefreshTests: XCTestCase {
    private func pairedModel() -> AppModel {
        let c = Credentials(relay: URL(string: "https://relay.test")!, phoneId: "ph_refresh01", token: "orn_refresh", phoneName: "Test")
        Keychain.save(c)
        StubProtocol.handler = { _ in (200, Data(#"{"items":[]}"#.utf8)) }
        let m = AppModel(useMock: false, session: StubProtocol.session())
        m.retryDelay = .milliseconds(20)
        return m
    }
    override func tearDown() async throws { Keychain.delete(); StubProtocol.failNext = 0 }

    func testColdStartFirstFailureRetriesBeforeTheBanner() async {
        let m = pairedModel()
        StubProtocol.failNext = 1
        await m.refresh()
        XCTAssertNil(m.message, "one early network failure must not show the banner")
        XCTAssertTrue(m.hasLoaded)
    }

    func testStillOfflineAfterTheRetryShowsTheBanner() async {
        let m = pairedModel()
        StubProtocol.failNext = 100
        await m.refresh()
        XCTAssertNotNil(m.message)
        XCTAssertFalse(m.hasLoaded)
    }

    func testOpenChatKeepsRefreshingUntilItCloses() async throws {
        let m = pairedModel()
        let t = Task { await m.watchWhileOpen(every: .milliseconds(30)) }
        try await Task.sleep(for: .milliseconds(300))
        t.cancel()
        try await Task.sleep(for: .milliseconds(150))   // a request already in flight may still land
        let n = StubProtocol.seen.filter { $0.url?.path == "/v1/phone/updates" }.count
        XCTAssertGreaterThanOrEqual(n, 3, "an open chat polls the relay by itself")
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertEqual(StubProtocol.seen.filter { $0.url?.path == "/v1/phone/updates" }.count, n, "closing the chat stops it")
    }
}
