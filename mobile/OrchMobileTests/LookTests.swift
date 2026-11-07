import XCTest
@testable import OrchMobile

/// Replays contracts/vectors/look-v1.json (default + render) against Look.swift.
final class LookTests: XCTestCase {
    private func vectors() throws -> [String: Any] {
        let url = Bundle(for: BundleToken.self).url(forResource: "look-v1", withExtension: "json")!
        return try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
    }

    func testDefaultVectors() throws {
        let rows = try vectors()["default"] as! [[String: Any]]
        XCTAssertGreaterThan(rows.count, 10)
        for r in rows {
            let name = r["name"] as! String, why = r["why"] as? String ?? ""
            XCTAssertEqual(Look.djb2(name), UInt32(truncating: r["djb2_32"] as! NSNumber), "djb2 \(name) \(why)")
            XCTAssertEqual(Look.defaultColor(for: name), r["color"] as? String, "colour \(name) \(why)")
            XCTAssertEqual(Look.letter(for: name), r["letter"] as? String, "letter \(name) \(why)")
        }
    }

    func testRenderVectors() throws {
        let rows = try vectors()["render"] as! [[String: Any]]
        for r in rows {
            let name = r["name"] as! String, why = r["why"] as? String ?? ""
            let shown = r["shown"] as! [String: Any]
            let got = Look.shown(icon: r["icon"] as? String, color: r["color"] as? String, name: name)
            XCTAssertEqual(got.icon, shown["icon"] as? String, "icon \(name) \(why)")
            XCTAssertEqual(got.color, shown["color"] as? String, "colour \(name) \(why)")
            XCTAssertEqual(got.letter, shown["letter"] as? String, "letter \(name) \(why)")
        }
    }

    func testEveryIconHasAnImage() {
        for id in LookData.iconIds { XCTAssertNotNil(UIImage(named: "look-\(id)"), "asset look-\(id)") }
        XCTAssertEqual(LookData.iconIds.count, 100)
    }

    func testWorkspaceDecodesLookAndOlderServer() throws {
        let withLook = Data(#"{"id":"ws_a","name":"Finance","description":"","tags":[],"online":true,"last_seen":null,"open_questions":0,"muted_until":null,"icon":"wallet","color":"amber"}"#.utf8)
        let w = try JSONCoding.decoder.decode(Workspace.self, from: withLook)
        XCTAssertEqual(w.icon, "wallet"); XCTAssertEqual(w.color, "amber")
        let old = Data(#"{"id":"ws_a","name":"Finance","description":"","tags":[],"online":true,"last_seen":null,"open_questions":0}"#.utf8)
        let o = try JSONCoding.decoder.decode(Workspace.self, from: old)
        XCTAssertNil(o.icon); XCTAssertNil(o.color)
    }
}

/// N4: the SVGs inside the asset catalog are byte for byte the contract's (the tests run on the Mac, so the repo is readable).
final class LookAssetSourceTests: XCTestCase {
    func testCatalogSvgsMatchContractBytes() throws {
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let contract = repo.appendingPathComponent("contracts/look/icons")
        let catalog = repo.appendingPathComponent("mobile/OrchMobile/Assets.xcassets/WorkspaceIcons")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: contract.path), "repo not readable from the test host")
        let ids = try FileManager.default.contentsOfDirectory(atPath: contract.path).filter { $0.hasSuffix(".svg") }.map { String($0.dropLast(4)) }
        XCTAssertEqual(Set(ids), LookData.iconIds)
        for id in ids {
            let a = try Data(contentsOf: contract.appendingPathComponent("\(id).svg"))
            let b = try Data(contentsOf: catalog.appendingPathComponent("look-\(id).imageset/\(id).svg"))
            XCTAssertEqual(a, b, "\(id).svg differs: run mobile/scripts/gen_look_assets.py")
        }
    }
}
