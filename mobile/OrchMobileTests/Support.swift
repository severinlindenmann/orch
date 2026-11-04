import Foundation
@testable import OrchMobile

/// One entry of contracts/review/relay-api.examples.json.
struct Example {
    let method: String, path: String
    let requestBody: Any?
    let status: Int
    let responseData: Data

    static func all() throws -> [Example] {
        let url = Bundle(for: BundleToken.self).url(forResource: "relay-api.examples", withExtension: "json")!
        let arr = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [[String: Any]]
        return try arr.map { e in
            let req = e["request"] as! [String: Any], resp = e["response"] as! [String: Any]
            let body = resp["body"]
            let data: Data
            if let str = body as? String { data = Data(str.utf8) }
            else if body is NSNull || body == nil { data = Data() }
            else {
                guard JSONSerialization.isValidJSONObject(body!) else { throw NSError(domain: "fixture", code: 1, userInfo: [NSLocalizedDescriptionKey: "bad fixture body"]) }
                data = try JSONSerialization.data(withJSONObject: body!)
            }
            return Example(method: req["method"] as! String, path: req["path"] as! String, requestBody: req["body"],
                           status: resp["status"] as! Int, responseData: data)
        }
    }

    static func find(_ method: String, _ path: String) throws -> Example {
        try all().first { $0.method == method && $0.path == path }!
    }
    /// Several examples can share method and path (the 201 and the 409 answer): pick by status.
    static func find(_ method: String, _ path: String, status: Int) throws -> Example {
        try all().first { $0.method == method && $0.path == path && $0.status == status }!
    }
}
final class BundleToken {}

/// URLProtocol that answers from a closure and records the request.
final class StubProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var handler: ((URLRequest) -> (Int, Data))?
    nonisolated(unsafe) static var seen: [URLRequest] = []
    nonisolated(unsafe) static var seenBodies: [Data] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var body = request.httpBody
        if body == nil, let s = request.httpBodyStream {
            s.open(); var d = Data(); var buf = [UInt8](repeating: 0, count: 4096)
            while s.hasBytesAvailable { let n = s.read(&buf, maxLength: buf.count); if n <= 0 { break }; d.append(buf, count: n) }
            s.close(); body = d
        }
        Self.seen.append(request); Self.seenBodies.append(body ?? Data())
        let (status, data) = Self.handler?(request) ?? (500, Data())
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}

    static func session() -> URLSession {
        let c = URLSessionConfiguration.ephemeral; c.protocolClasses = [StubProtocol.self]
        seen = []; seenBodies = []
        return URLSession(configuration: c)
    }
}
