import SwiftUI
import WebKit
import PDFKit
import QuickLook

// The viewer owns loading and temporary files; surfaces only display the result.
enum ArtifactSurfaceContent {
    case publish(PublishContent)
    case data(Data, name: String, mime: String)
    case quickLook(URL)
    case shareOnly(URL, name: String, size: Int)
    case link(URL)
}

/// Serves the decrypted files of one published page under `orch-page://page/<path>`. A single page is a bundle of one file.
final class PageSchemeHandler: NSObject, WKURLSchemeHandler {
    nonisolated(unsafe) var bundle: PublishBundle
    init(bundle: PublishBundle) { self.bundle = bundle }

    static func bundle(for content: PublishContent) -> PublishBundle? {
        switch content {
        case .bundle(let b, _): return b
        case .page(let html, _): return PublishBundle(entry: "index.html", files: [.init(path: "index.html", type: "text/html", data: Data(html.utf8))])
        case .file: return nil
        }
    }
    static let base = URL(string: "orch-page://page/")!

    func webView(_ webView: WKWebView, start urlSchemeTask: any WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url else { return }
        let path = String((url.path.removingPercentEncoding ?? url.path).drop(while: { $0 == "/" }))
        let file = url.host == "page" ? bundle.file(at: path) : nil
        let served = file.map { NetworkBlock.serve(type: $0.type, data: $0.data) }
        let headers = ["Content-Type": served?.type ?? "text/plain", "Content-Security-Policy": NetworkBlock.csp, "X-Content-Type-Options": "nosniff",
                       "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"]
        guard let response = HTTPURLResponse(url: url, statusCode: file == nil ? 404 : 200, httpVersion: "HTTP/1.1", headerFields: headers) else { return }
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(served?.data ?? Data())
        urlSchemeTask.didFinish()
    }
    func webView(_ webView: WKWebView, stop urlSchemeTask: any WKURLSchemeTask) {}
}

/// The one way a published page is shown: no stored data, no network (rule list + CSP + no WebRTC), pins only in their own world.
@MainActor
enum PublishWebView {
    static func make(handler: PageSchemeHandler, pins: (WKScriptMessageHandler)?) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.setURLSchemeHandler(handler, forURLScheme: NetworkBlock.scheme)
        let controller = WKUserContentController()
        controller.addUserScript(WKUserScript(source: NetworkBlock.noHints, injectionTime: .atDocumentStart, forMainFrameOnly: false, in: NetworkBlock.hintWorld))
        controller.addUserScript(WKUserScript(source: NetworkBlock.noWebRTC, injectionTime: .atDocumentStart, forMainFrameOnly: false))
        controller.addUserScript(WKUserScript(source: AnchorScript.source, injectionTime: .atDocumentStart, forMainFrameOnly: true, in: AnchorScript.world))
        if let pins { controller.add(pins, contentWorld: AnchorScript.world, name: AnchorScript.handler) }
        configuration.userContentController = controller
        return WKWebView(frame: .zero, configuration: configuration)
    }
    /// Compiles and adds the block list; false when it could not be made (then nothing may load).
    static func block(_ view: WKWebView) async -> Bool {
        guard let rules = try? await WKContentRuleListStore.default().compileContentRuleList(
            forIdentifier: NetworkBlock.identifier, encodedContentRuleList: NetworkBlock.rules) else { return false }
        view.configuration.userContentController.add(rules)
        return true
    }
    static func isLocal(_ url: URL?) -> Bool { url?.scheme?.lowercased() == NetworkBlock.scheme }
}

@MainActor
struct HTMLSurface: UIViewRepresentable {
    let content: ArtifactSurfaceContent
    var commentMode: Bool
    let store: PinStore
    var onFailure: (String) -> Void = { _ in }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let c = context.coordinator
        let view = PublishWebView.make(handler: c.pages, pins: c)
        view.navigationDelegate = c
        view.isInspectable = false
        view.isOpaque = false
        view.backgroundColor = .white
        view.scrollView.backgroundColor = .white
        view.scrollView.contentInsetAdjustmentBehavior = .never
        view.allowsBackForwardNavigationGestures = false
        store.addAtCenter = { [weak view] in view?.evaluateJavaScript("window.__orch && window.__orch.placeCenter();", in: nil, in: AnchorScript.world, completionHandler: nil) }
        c.load(view)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.sync(view)
    }

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        coordinator.loadTask?.cancel()
        view.stopLoading()
        view.navigationDelegate = nil
        view.configuration.userContentController.removeScriptMessageHandler(forName: AnchorScript.handler, contentWorld: AnchorScript.world)
    }

    @MainActor final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        var parent: HTMLSurface
        let pages: PageSchemeHandler
        var loadTask: Task<Void, Never>?
        private var lastMode: Bool?
        private var lastPins: [PinDraftItem]?
        init(_ parent: HTMLSurface) {
            self.parent = parent
            var bundle = PublishBundle(entry: "index.html", files: [])
            if case .publish(let content) = parent.content, let b = PageSchemeHandler.bundle(for: content) { bundle = b }
            pages = PageSchemeHandler(bundle: bundle)
        }

        func load(_ view: WKWebView) {
            loadTask = Task { @MainActor [weak self, weak view] in
                guard let self, let view else { return }
                guard await PublishWebView.block(view), !Task.isCancelled else {
                    if !Task.isCancelled { self.parent.onFailure("Could not prepare this preview. Try again.") }
                    return
                }
                view.load(URLRequest(url: PageSchemeHandler.base.appendingPathComponent(self.pages.bundle.entry)))
            }
        }

        func sync(_ view: WKWebView, force: Bool = false) {
            if force || lastMode != parent.commentMode {
                view.evaluateJavaScript(AnchorScript.setMode(parent.commentMode), in: nil, in: AnchorScript.world, completionHandler: nil)
                lastMode = parent.commentMode
            }
            if force || lastPins != parent.store.pins {
                view.evaluateJavaScript(AnchorScript.setPins(parent.store.pins), in: nil, in: AnchorScript.world, completionHandler: nil)
                lastPins = parent.store.pins
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard parent.commentMode, message.frameInfo.isMainFrame else { return }
            if let body = message.body as? [String: Any], body["kind"] as? String == "edit", let n = body["n"] as? Int { parent.store.edit(n) }
            else if let pin = AnchorMaker.html(fromScript: message.body) { parent.store.beginPin(anchor: pin.anchor, place: pin.place) }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { sync(webView, force: true) }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            // Only the decrypted local document; links in the page (any other address) are refused.
            decisionHandler(PublishWebView.isLocal(navigationAction.request.url) ? .allow : .cancel)
        }
    }
}

@MainActor
struct PDFSurface: UIViewRepresentable {
    let data: Data
    var commentMode: Bool
    let store: PinStore
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.document = PDFDocument(data: data)
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.autoScales = true
        view.backgroundColor = .white
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tap(_:)))
        tap.cancelsTouchesInView = false
        tap.delegate = context.coordinator
        view.addGestureRecognizer(tap)
        let store = self.store
        store.addAtCenter = { [weak view] in
            guard let view, let doc = view.document, let page = view.currentPage ?? doc.page(at: 0) else { return }
            let n = doc.index(for: page) + 1
            store.beginPin(anchor: AnchorMaker.pdf(page: n, x: 0.5, y: 0.5), place: .init(x: 0.5, y: 0.5, page: n))
        }
        context.coordinator.redraw(view)
        return view
    }
    func updateUIView(_ view: PDFView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.redraw(view)
    }

    @MainActor final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        var parent: PDFSurface
        var lastPins: [PinDraftItem]?
        init(_ parent: PDFSurface) { self.parent = parent }
        func redraw(_ view: PDFView) {
            guard lastPins != parent.store.pins, let document = view.document else { return }
            lastPins = parent.store.pins
            for i in 0..<document.pageCount {
                guard let page = document.page(at: i) else { continue }
                for annotation in page.annotations where annotation is PinAnnotation { page.removeAnnotation(annotation) }
                let box = page.bounds(for: .cropBox)
                for pin in parent.store.pins where pin.place.page == i + 1 {
                    let point = CGPoint(x: box.minX + box.width * pin.place.x, y: box.maxY - box.height * pin.place.y)
                    page.addAnnotation(PinAnnotation(number: pin.n, center: point))
                }
            }
        }
        @objc func tap(_ recognizer: UITapGestureRecognizer) {
            guard parent.commentMode, let view = recognizer.view as? PDFView,
                  let document = view.document else { return }
            let point = recognizer.location(in: view)
            // Measure in view points, so the hit target remains usable at every zoom.
            for i in 0..<document.pageCount {
                guard let page = document.page(at: i) else { continue }
                for case let pin as PinAnnotation in page.annotations {
                    let center = view.convert(CGPoint(x: pin.bounds.midX, y: pin.bounds.midY), from: page)
                    if hypot(center.x - point.x, center.y - point.y) <= 22 { parent.store.edit(pin.number); return }
                }
            }
            guard let page = view.page(for: point, nearest: true) else { return }
            let p = view.convert(point, to: page), box = page.bounds(for: .cropBox)
            guard box.width > 0, box.height > 0 else { return }
            let x = AnchorMaker.fraction((p.x - box.minX) / box.width)
            let y = AnchorMaker.fraction((box.maxY - p.y) / box.height)
            let n = document.index(for: page) + 1
            parent.store.beginPin(anchor: AnchorMaker.pdf(page: n, x: x, y: y), place: .init(x: x, y: y, page: n))
        }
        nonisolated func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                                          shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool { true }
    }
}

// PDFKit can draw on a background thread. Capture immutable drawing values instead of accessing UI state there.
final class PinAnnotation: PDFAnnotation {
    let number: Int
    private let fill: CGColor
    private let ink: CGColor
    @MainActor init(number: Int, center: CGPoint) {
        self.number = number
        fill = UIColor(Theme.brand).cgColor
        ink = UIColor(Theme.onBrand).cgColor
        super.init(bounds: CGRect(x: center.x - 14, y: center.y - 14, width: 28, height: 28), forType: .stamp, withProperties: nil)
        contents = "Comment \(number)"
    }
    required init?(coder: NSCoder) { return nil }
    override func draw(with box: PDFDisplayBox, in context: CGContext) {
        context.saveGState()
        context.setFillColor(fill)
        context.fillEllipse(in: bounds)
        // UIKit's text drawing needs a top-left coordinate system in a PDF context.
        context.translateBy(x: bounds.minX, y: bounds.maxY)
        context.scaleBy(x: 1, y: -1)
        UIGraphicsPushContext(context)
        let text = "\(number)" as NSString
        let attributes: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 14, weight: .bold), .foregroundColor: UIColor(cgColor: ink)]
        let size = text.size(withAttributes: attributes)
        text.draw(at: CGPoint(x: (28 - size.width) / 2, y: (28 - size.height) / 2), withAttributes: attributes)
        UIGraphicsPopContext()
        context.restoreGState()
    }
}

@MainActor
struct ImageSurface: UIViewRepresentable {
    let data: Data
    var commentMode: Bool
    let store: PinStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIView(context: Context) -> ImageScrollView {
        let view = ImageScrollView()
        view.imageView.image = UIImage(data: data)
        view.delegate = context.coordinator
        let doubleTap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.doubleTap(_:)))
        doubleTap.numberOfTapsRequired = 2
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tap(_:)))
        tap.require(toFail: doubleTap)
        tap.cancelsTouchesInView = false
        view.addGestureRecognizer(tap)
        view.addGestureRecognizer(doubleTap)
        let store = self.store
        store.addAtCenter = { store.beginPin(anchor: AnchorMaker.image(x: 0.5, y: 0.5), place: .init(x: 0.5, y: 0.5)) }
        context.coordinator.redraw(view)
        return view
    }
    func updateUIView(_ view: ImageScrollView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.redraw(view)
    }
    @MainActor final class Coordinator: NSObject, UIScrollViewDelegate {
        var parent: ImageSurface
        var lastPins: [PinDraftItem]?
        init(_ parent: ImageSurface) { self.parent = parent }
        func viewForZooming(in scrollView: UIScrollView) -> UIView? { (scrollView as? ImageScrollView)?.imageView }
        func scrollViewDidZoom(_ scrollView: UIScrollView) { (scrollView as? ImageScrollView)?.centerImage() }
        func redraw(_ view: ImageScrollView) {
            guard lastPins != parent.store.pins else { return }
            lastPins = parent.store.pins
            view.pins = parent.store.pins
            view.imageView.subviews.forEach { $0.removeFromSuperview() }
            for pin in parent.store.pins {
                let badge = UILabel()
                badge.tag = pin.n
                badge.text = "\(pin.n)"
                badge.font = .systemFont(ofSize: 14, weight: .bold)
                badge.textAlignment = .center
                badge.backgroundColor = UIColor(Theme.brand)
                badge.textColor = UIColor(Theme.onBrand)
                badge.layer.cornerRadius = 14
                badge.clipsToBounds = true
                badge.bounds = CGRect(x: 0, y: 0, width: 28, height: 28)
                badge.isAccessibilityElement = true
                badge.accessibilityLabel = "Comment \(pin.n): \(pin.text)"
                view.imageView.addSubview(badge)
            }
            view.centerImage()
        }
        @objc func doubleTap(_ recognizer: UITapGestureRecognizer) {
            guard let view = recognizer.view as? ImageScrollView else { return }
            if view.zoomScale > 1 { view.setZoomScale(1, animated: !parent.reduceMotion) }
            else {
                let p = recognizer.location(in: view.imageView)
                view.zoom(to: CGRect(x: p.x - view.bounds.width / 4, y: p.y - view.bounds.height / 4,
                                     width: view.bounds.width / 2, height: view.bounds.height / 2), animated: !parent.reduceMotion)
            }
        }
        @objc func tap(_ recognizer: UITapGestureRecognizer) {
            guard parent.commentMode, let view = recognizer.view as? ImageScrollView else { return }
            let point = recognizer.location(in: view)
            for badge in view.imageView.subviews {
                let center = view.imageView.convert(badge.center, to: view)
                if hypot(point.x - center.x, point.y - center.y) <= 22 { parent.store.edit(badge.tag); return }
            }
            let p = recognizer.location(in: view.imageView), bounds = view.imageView.bounds
            guard bounds.width > 0, bounds.height > 0, bounds.contains(p) else { return }
            let x = Double(p.x / bounds.width), y = Double(p.y / bounds.height)
            parent.store.beginPin(anchor: AnchorMaker.image(x: x, y: y), place: .init(x: x, y: y))
        }
    }
}

@MainActor final class ImageScrollView: UIScrollView {
    let imageView = UIImageView()
    var pins: [PinDraftItem] = []
    private var viewport = CGSize.zero
    override init(frame: CGRect) {
        super.init(frame: frame)
        minimumZoomScale = 1; maximumZoomScale = 6
        contentInsetAdjustmentBehavior = .never
        backgroundColor = .white
        imageView.contentMode = .scaleAspectFit
        imageView.isUserInteractionEnabled = true
        addSubview(imageView)
    }
    required init?(coder: NSCoder) { return nil }
    override func layoutSubviews() {
        super.layoutSubviews()
        if viewport != bounds.size, bounds.width > 0, bounds.height > 0, let image = imageView.image,
           image.size.width > 0, image.size.height > 0 {
            viewport = bounds.size
            setZoomScale(1, animated: false)
            let scale = min(bounds.width / image.size.width, bounds.height / image.size.height)
            imageView.frame = CGRect(origin: .zero, size: CGSize(width: image.size.width * scale, height: image.size.height * scale))
            contentSize = imageView.bounds.size
        }
        centerImage()
    }
    func centerImage() {
        imageView.center = CGPoint(x: max(contentSize.width, bounds.width) / 2, y: max(contentSize.height, bounds.height) / 2)
        for badge in imageView.subviews {
            guard let pin = pins.first(where: { $0.n == badge.tag }) else { continue }
            badge.center = CGPoint(x: imageView.bounds.width * pin.place.x, y: imageView.bounds.height * pin.place.y)
            badge.transform = CGAffineTransform(scaleX: 1 / zoomScale, y: 1 / zoomScale)
        }
    }
}

@MainActor
struct QuickLookPreview: UIViewControllerRepresentable {
    let url: URL
    func makeCoordinator() -> Coordinator { Coordinator(url: url) }
    func makeUIViewController(context: Context) -> QLPreviewController {
        let controller = QLPreviewController()
        controller.dataSource = context.coordinator
        return controller
    }
    func updateUIViewController(_ controller: QLPreviewController, context: Context) {
        if context.coordinator.url != url { context.coordinator.url = url; controller.reloadData() }
    }
    @MainActor final class Coordinator: NSObject, QLPreviewControllerDataSource {
        var url: URL
        init(url: URL) { self.url = url }
        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }
        func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> any QLPreviewItem { url as NSURL }
    }
}
