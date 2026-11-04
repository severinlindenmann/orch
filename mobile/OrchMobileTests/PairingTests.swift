import XCTest
@testable import OrchMobile

final class PairingTests: XCTestCase {
    func testParsesContractLink() throws {
        let l = try PairingLink("orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V")
        XCTAssertEqual(l.relay.absoluteString, "https://relay.severin.io"); XCTAssertEqual(l.code, "pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V"); XCTAssertEqual(l.host, "relay.severin.io")
    }
    func testRoundTripSample() throws { XCTAssertEqual(try PairingLink(PairingLink.sample.link), PairingLink.sample) }
    func testRejectsBadLinks() {
        for bad in ["", "https://relay.severin.io", "orch://pair?code=pc_x12345678", "orch://pair?relay=https%3A%2F%2Fa.io",
                    "orch://other?relay=https%3A%2F%2Fa.io&code=pc_abcdefgh", "orch://pair?relay=ftp%3A%2F%2Fa.io&code=pc_abcdefgh",
                    "orch://pair?relay=https%3A%2F%2Fa.io&code=xx_abcdefgh"] {
            XCTAssertThrowsError(try PairingLink(bad), bad)
        }
    }
    func testDecodesContractExampleLink() throws {
        let ex = try Example.find("POST", "/admin/api/phones")
        let link = (try JSONSerialization.jsonObject(with: ex.responseData) as! [String: Any])["link"] as! String
        XCTAssertNoThrow(try PairingLink(link))
    }
}
