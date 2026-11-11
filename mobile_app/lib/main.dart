import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';

void main() => runApp(const SmartAgricultureApp());

class SmartAgricultureApp extends StatelessWidget {
  const SmartAgricultureApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Smart Agriculture AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: Colors.green), useMaterial3: true),
      home: const FarmHome(),
    );
  }
}

class ApiService {
  // Android emulator -> 10.0.2.2. Physical phone -> computer's LAN IP.
  static const String baseUrl = 'http://10.0.2.2:8000';

  static Future<Map<String, dynamic>> get(String path) async {
    final response = await http.get(Uri.parse('$baseUrl$path')).timeout(const Duration(seconds: 12));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('API ${response.statusCode}: ${response.body}');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  static Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body) async {
    final response = await http.post(Uri.parse('$baseUrl$path'),
      headers: {'Content-Type': 'application/json'}, body: jsonEncode(body))
      .timeout(const Duration(seconds: 12));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('API ${response.statusCode}: ${response.body}');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  static Future<Map<String, dynamic>> analyzeImage(File file, String crop) async {
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl/api/disease/analyze'));
    request.fields['crop'] = crop;
    request.files.add(await http.MultipartFile.fromPath('image', file.path));
    final streamed = await request.send().timeout(const Duration(seconds: 30));
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('API ${response.statusCode}: ${response.body}');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }
}

class FarmHome extends StatefulWidget {
  const FarmHome({super.key});
  @override
  State<FarmHome> createState() => _FarmHomeState();
}

class _FarmHomeState extends State<FarmHome> {
  int index = 0;
  String crop = 'Tomato';
  String location = 'Chennai';
  String stage = 'Vegetative';
  DateTime sowingDate = DateTime.now().subtract(const Duration(days: 35));
  final moisture = TextEditingController(text: '38');
  final airTemp = TextEditingController(text: '31.5');
  final humidity = TextEditingController(text: '65');
  final soilTemp = TextEditingController(text: '27');
  final rain = TextEditingController(text: '0');
  Map<String, dynamic>? weather;
  Map<String, dynamic>? irrigation;
  Map<String, dynamic>? maturity;
  List<dynamic> readings = [];
  bool loading = false;
  String? error;
  File? leafImage;
  Map<String, dynamic>? disease;
  final picker = ImagePicker();

  static const crops = ['Tomato', 'Rice', 'Wheat', 'Chilli', 'Groundnut', 'Maize'];
  static const stages = ['Seedling', 'Vegetative', 'Flowering', 'Fruiting / grain filling', 'Maturity'];

  @override
  void initState() {
    super.initState();
    refreshData();
  }

  @override
  void dispose() {
    moisture.dispose(); airTemp.dispose(); humidity.dispose(); soilTemp.dispose(); rain.dispose();
    super.dispose();
  }

  Future<void> runBusy(Future<void> Function() task) async {
    setState(() { loading = true; error = null; });
    try { await task(); } catch (e) { setState(() => error = e.toString()); }
    if (mounted) setState(() => loading = false);
  }

  Future<void> refreshData() async {
    await runBusy(() async {
      final w = await ApiService.get('/api/weather?location=${Uri.encodeQueryComponent(location)}');
      final r = await http.get(Uri.parse('${ApiService.baseUrl}/api/sensor-readings?limit=30')).timeout(const Duration(seconds: 12));
      if (r.statusCode != 200) throw Exception(r.body);
      setState(() { weather = w; readings = jsonDecode(r.body) as List<dynamic>; });
    });
  }

  Future<void> requestIrrigation() async {
    await runBusy(() async {
      final result = await ApiService.post('/api/irrigation/recommend', {
        'crop': crop,
        'soil_moisture': double.parse(moisture.text),
        'air_temperature': double.parse(airTemp.text),
        'humidity': double.parse(humidity.text),
        'forecast_rain_mm': double.parse(rain.text),
        'growth_stage': stage,
        'soil_type': 'Unknown'
      });
      setState(() => irrigation = result);
    });
  }

  Future<void> requestMaturity() async {
    await runBusy(() async {
      final result = await ApiService.post('/api/crop/maturity', {
        'crop': crop,
        'sowing_date': DateFormat('yyyy-MM-dd').format(sowingDate),
        'growth_stage': stage
      });
      setState(() => maturity = result);
    });
  }

  Future<void> pickLeafImage() async {
    final x = await picker.pickImage(source: ImageSource.gallery, imageQuality: 85);
    if (x != null && mounted) setState(() { leafImage = File(x.path); disease = null; });
  }

  Future<void> analyzeLeaf() async {
    if (leafImage == null) return;
    await runBusy(() async {
      final result = await ApiService.analyzeImage(leafImage!, crop);
      setState(() => disease = result);
    });
  }

  Widget panel(Widget child) => Card(child: Padding(padding: const EdgeInsets.all(16), child: child));
  Widget metric(String label, String value, IconData icon) => Expanded(
    child: panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Icon(icon, color: Colors.green), const SizedBox(height: 8),
      Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      Text(label, style: const TextStyle(color: Colors.black54))
    ]))
  );
  Widget field(String label, TextEditingController controller) => TextField(
    controller: controller, keyboardType: const TextInputType.numberWithOptions(decimal: true),
    decoration: InputDecoration(labelText: label, border: const OutlineInputBorder())
  );
  Widget errorBanner() => error == null ? const SizedBox.shrink() : panel(
    Text('Connection / processing error:\n$error', style: const TextStyle(color: Colors.red)));

  @override
  Widget build(BuildContext context) {
    final pages = [overviewPage(), irrigationPage(), cropPage(), diseasePage(), sensorsPage()];
    return Scaffold(
      appBar: AppBar(title: const Text('Smart Agriculture AI'), actions: [
        IconButton(onPressed: loading ? null : refreshData, icon: const Icon(Icons.refresh))
      ]),
      body: loading ? const Center(child: CircularProgressIndicator()) : ListView(
        padding: const EdgeInsets.all(12), children: [errorBanner(), pages[index]]
      ),
      bottomNavigationBar: NavigationBar(selectedIndex: index, onDestinationSelected: (v) => setState(() => index = v),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), selectedIcon: Icon(Icons.dashboard), label: 'Overview'),
          NavigationDestination(icon: Icon(Icons.water_drop_outlined), selectedIcon: Icon(Icons.water_drop), label: 'Irrigation'),
          NavigationDestination(icon: Icon(Icons.grass_outlined), selectedIcon: Icon(Icons.grass), label: 'Crop'),
          NavigationDestination(icon: Icon(Icons.local_florist_outlined), selectedIcon: Icon(Icons.local_florist), label: 'Disease'),
          NavigationDestination(icon: Icon(Icons.sensors), selectedIcon: Icon(Icons.sensors), label: 'Sensors'),
        ]),
    );
  }

  Widget overviewPage() => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    const Text('Farm overview', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
    const SizedBox(height: 8),
    panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('Farm settings', style: TextStyle(fontWeight: FontWeight.bold)),
      DropdownButtonFormField<String>(value: crop, decoration: const InputDecoration(labelText: 'Crop'),
        items: crops.map((x) => DropdownMenuItem(value: x, child: Text(x))).toList(),
        onChanged: (v) { if (v != null) setState(() { crop = v; }); }),
      TextField(controller: TextEditingController(text: location), decoration: const InputDecoration(labelText: 'Forecast location'),
        onChanged: (v) => location = v),
      const SizedBox(height: 8),
      FilledButton.icon(onPressed: refreshData, icon: const Icon(Icons.cloud_download), label: const Text('Refresh weather'))
    ])),
    Row(children: [
      metric('Temperature', weather?['ok'] == true ? '${weather?['temperature_c']} °C' : 'Unavailable', Icons.thermostat),
      metric('Humidity', weather?['ok'] == true ? '${weather?['humidity_pct']}%' : '--', Icons.water),
    ]),
    Row(children: [
      metric('Rain next 6 h', weather?['ok'] == true ? '${weather?['rain_next_6h_mm']} mm' : '--', Icons.cloud),
      metric('Crop', crop, Icons.eco),
    ]),
    if (weather?['ok'] == false) panel(Text('Weather unavailable: ${weather?['error'] ?? 'No data'}')),
    panel(const Text('The app can work with manual readings now. Sensor values become live when the ESP32 is connected to the backend.'))
  ]);

  Widget irrigationPage() => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    const Text('Irrigation advisor', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
    const SizedBox(height: 8),
    panel(Column(children: [
      field('Soil moisture (%)', moisture), const SizedBox(height: 10),
      field('Air temperature (°C)', airTemp), const SizedBox(height: 10),
      field('Humidity (%)', humidity), const SizedBox(height: 10),
      field('Soil temperature (°C) — recorded for later use', soilTemp), const SizedBox(height: 10),
      field('Forecast rain next few hours (mm)', rain), const SizedBox(height: 10),
      DropdownButtonFormField<String>(value: stage, decoration: const InputDecoration(labelText: 'Growth stage'),
        items: stages.map((x) => DropdownMenuItem(value: x, child: Text(x))).toList(),
        onChanged: (v) { if (v != null) setState(() => stage = v); }),
      const SizedBox(height: 12),
      SizedBox(width: double.infinity, child: FilledButton(onPressed: requestIrrigation, child: const Text('Get irrigation recommendation')))
    ])),
    if (irrigation != null) panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('Recommendation', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
      Text('${irrigation!['decision']}', style: const TextStyle(fontSize: 20, color: Colors.green, fontWeight: FontWeight.bold)),
      Text('${irrigation!['summary']}'),
      const SizedBox(height: 8),
      Text('Estimated water: ${irrigation!['estimated_water_mm']} mm'),
      Text('${irrigation!['confidence']}'),
      const Divider(),
      const Text('Why this recommendation?', style: TextStyle(fontWeight: FontWeight.bold)),
      ...(irrigation!['reasons'] as List<dynamic>).map((x) => Text('• $x')),
      const SizedBox(height: 8), Text('${irrigation!['warning']}', style: const TextStyle(color: Colors.deepOrange))
    ]))
  ]);

  Widget cropPage() => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    const Text('Crop growth & harvest', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
    panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Sowing date: ${DateFormat('dd MMM yyyy').format(sowingDate)}'),
      OutlinedButton.icon(onPressed: () async {
        final picked = await showDatePicker(context: context, initialDate: sowingDate,
          firstDate: DateTime(2000), lastDate: DateTime.now());
        if (picked != null) setState(() => sowingDate = picked);
      }, icon: const Icon(Icons.calendar_month), label: const Text('Choose sowing date')),
      DropdownButtonFormField<String>(value: stage, decoration: const InputDecoration(labelText: 'Growth stage'),
        items: stages.map((x) => DropdownMenuItem(value: x, child: Text(x))).toList(),
        onChanged: (v) { if (v != null) setState(() => stage = v); }),
      const SizedBox(height: 12),
      SizedBox(width: double.infinity, child: FilledButton(onPressed: requestMaturity, child: const Text('Estimate harvest window')))
    ])),
    if (maturity != null) panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Estimated days remaining: ${maturity!['estimated_days_remaining']}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      Text('Estimated maturity date: ${maturity!['estimated_maturity_date']}'),
      Text('${maturity!['message']}'),
      const SizedBox(height: 8), Text('${maturity!['warning']}', style: const TextStyle(color: Colors.deepOrange))
    ])),
    panel(const Text('For a reliable prediction, crop variety, local growing conditions and actual maturity/harvest records must be used to calibrate or train the model.'))
  ]);

  Widget diseasePage() => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    const Text('Plant disease screening', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
    panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Selected crop: $crop'),
      const SizedBox(height: 8),
      if (leafImage != null) Image.file(leafImage!, height: 220, fit: BoxFit.contain)
      else const Text('Choose a clear image of the affected leaf.'),
      const SizedBox(height: 8),
      Wrap(spacing: 8, children: [
        OutlinedButton.icon(onPressed: pickLeafImage, icon: const Icon(Icons.photo_library), label: const Text('Choose image')),
        FilledButton.icon(onPressed: leafImage == null ? null : analyzeLeaf, icon: const Icon(Icons.search), label: const Text('Analyze'))
      ]),
    ])),
    if (disease != null) panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(disease!['available'] == true ? 'Model result: ${disease!['predicted_class']}' : 'Model not ready',
        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
      if (disease!['confidence'] != null) Text('Model score: ${(100 * (disease!['confidence'] as num)).toStringAsFixed(1)}%'),
      Text('${disease!['message']}'),
      if (disease!['next_step'] != null) Text('${disease!['next_step']}')
    ])),
    panel(const Text('A disease model must be trained and evaluated before it can provide predictions. Any model output is a screening aid, not a confirmed diagnosis. Treatment guidance should be crop-specific and locally approved.'))
  ]);

  Widget sensorsPage() => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    const Text('Sensor readings', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
    FilledButton.icon(onPressed: refreshData, icon: const Icon(Icons.sync), label: const Text('Refresh readings')),
    if (readings.isEmpty) panel(const Text('No sensor readings in the database yet. You can add a test reading using the API docs.'))
    else ...readings.map((r) => panel(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${r['crop']} • ${r['timestamp']}', style: const TextStyle(fontWeight: FontWeight.bold)),
      Text('Soil moisture: ${r['soil_moisture']}%'),
      Text('Air temperature: ${r['air_temperature'] ?? '--'} °C • Humidity: ${r['humidity'] ?? '--'}%'),
      Text('Device: ${r['device_id'] ?? '--'} • Source: ${r['source'] ?? '--'}')
    ]))),
    panel(const Text('Future ESP32 integration: POST sensor readings to /api/sensor-readings. Pump control is intentionally disabled until device authentication and hardware safety interlocks are implemented.')),
    panel(const Text('Future pest module: this app can later display pest-monitoring events and experimental deterrent status. Acoustic deterrence effectiveness must be verified for each target species.'))
  ]);
}
