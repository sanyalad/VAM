import React, { useState, useEffect, useMemo } from 'react';
import { Plus, Save, Trash2, Upload, Download, Map, CheckSquare, Square, AlertCircle, Info, Search, Printer } from 'lucide-react';

interface Device {
  id: number;
  shop: string;
  name: string;
  model: string;
  scale: string;
  last_date: string;
  interval_mo: number;
  next_date: string;
  notes: string;
}

export default function App() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [checkedIds, setCheckedIds] = useState<Set<number>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  
  // Form state
  const [formData, setFormData] = useState<Partial<Device>>({
    shop: '', name: '', model: '', scale: '', last_date: '', interval_mo: 12, notes: ''
  });

  // Load from local storage on mount
  useEffect(() => {
    const saved = localStorage.getItem('kipia_devices');
    if (saved) {
      setDevices(JSON.parse(saved));
    }
  }, []);

  // Save to local storage on change
  useEffect(() => {
    localStorage.setItem('kipia_devices', JSON.stringify(devices));
  }, [devices]);

  const parseDate = (dateStr: string) => {
    const parts = dateStr.split('.');
    if (parts.length === 3) {
      return new Date(parseInt(parts[2]), parseInt(parts[1]) - 1, parseInt(parts[0]));
    }
    return new Date(NaN);
  };

  const formatDate = (date: Date) => {
    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const y = date.getFullYear();
    return `${d}.${m}.${y}`;
  };

  const calculateNextDate = (lastDateStr: string, intervalMo: number) => {
    const d = parseDate(lastDateStr);
    if (isNaN(d.getTime())) return '';
    d.setMonth(d.getMonth() + Number(intervalMo));
    return formatDate(d);
  };

  const handleSave = () => {
    if (!formData.shop || !formData.name || !formData.last_date || !formData.interval_mo) {
      alert("Заполните обязательные поля (Цех, Название, Дата, Интервал)");
      return;
    }

    const next_date = calculateNextDate(formData.last_date, formData.interval_mo);
    if (!next_date) {
      alert("Неверный формат даты (нужно ДД.ММ.ГГГГ)");
      return;
    }

    if (formData.id) {
      setDevices(devices.map(d => d.id === formData.id ? { ...formData, next_date } as Device : d));
    } else {
      const newDevice = { ...formData, id: Date.now(), next_date } as Device;
      setDevices([...devices, newDevice]);
    }
    handleClear();
  };

  const handleDelete = () => {
    if (formData.id && window.confirm("Удалить выбранный прибор?")) {
      setDevices(devices.filter(d => d.id !== formData.id));
      handleClear();
    }
  };

  const handleClear = () => {
    setFormData({ shop: '', name: '', model: '', scale: '', last_date: '', interval_mo: 12, notes: '' });
  };

  const toggleCheck = (id: number) => {
    const newChecked = new Set(checkedIds);
    if (newChecked.has(id)) newChecked.delete(id);
    else newChecked.add(id);
    setCheckedIds(newChecked);
  };

  const getRowColor = (device: Device) => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const nextD = parseDate(device.next_date);
    if (isNaN(nextD.getTime())) return '';

    const diffTime = nextD.getTime() - today.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays < 0) return 'bg-red-100 text-red-900'; // danger
    if (diffDays <= 30) return 'bg-yellow-100 text-yellow-900'; // warning
    if ((device.shop.includes('Ц47') || device.shop.includes('Ц66')) && diffDays <= 90) {
      return 'bg-blue-100 text-blue-900'; // info
    }
    return 'hover:bg-gray-50';
  };

  // Filter devices based on search query
  const filteredDevices = useMemo(() => {
    const query = searchQuery.toLowerCase();
    return devices.filter(d => 
      d.name.toLowerCase().includes(query) || 
      d.model.toLowerCase().includes(query) ||
      d.shop.toLowerCase().includes(query)
    );
  }, [devices, searchQuery]);

  const handlePrint = (type: 'ppr' | 'task') => {
    let itemsToPrint = [];
    let title = '';

    if (type === 'task') {
      itemsToPrint = devices.filter(d => checkedIds.has(d.id));
      title = 'Сменное задание КИПиА';
      if (itemsToPrint.length === 0) {
        alert('Сначала отметьте галочками (☑) приборы для сменного задания!');
        return;
      }
    } else {
      itemsToPrint = filteredDevices; // Print currently visible items
      title = 'График ППР (Планово-предупредительный ремонт)';
      if (itemsToPrint.length === 0) {
        alert('Нет данных для печати ППР!');
        return;
      }
    }

    const printWindow = window.open('', '_blank');
    if (!printWindow) {
      alert('Пожалуйста, разрешите всплывающие окна для печати.');
      return;
    }

    const html = `
      <html>
        <head>
          <title>${title}</title>
          <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            table { border-collapse: collapse; width: 100%; margin-top: 20px; font-size: 12px; }
            th, td { border: 1px solid black; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            h2 { text-align: center; }
            .footer { margin-top: 50px; display: flex; justify-content: space-between; }
            @media print {
              .no-print { display: none; }
            }
          </style>
        </head>
        <body>
          <button class="no-print" onclick="window.print()" style="padding: 10px 20px; font-size: 16px; cursor: pointer; margin-bottom: 20px;">🖨 Распечатать</button>
          <h2>${title}</h2>
          <p>Дата формирования: ${new Date().toLocaleDateString('ru-RU')} ${new Date().toLocaleTimeString('ru-RU', {hour: '2-digit', minute:'2-digit'})}</p>
          <table>
            <thead>
              <tr>
                <th>Цех</th>
                <th>Название</th>
                <th>Модель/Зав.№</th>
                <th>Шкала</th>
                <th>След. поверка</th>
                <th>Пометки</th>
              </tr>
            </thead>
            <tbody>
              ${itemsToPrint.map(d => `
                <tr>
                  <td>${d.shop}</td>
                  <td>${d.name}</td>
                  <td>${d.model}</td>
                  <td>${d.scale}</td>
                  <td><strong>${d.next_date}</strong></td>
                  <td>${d.notes}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
          <div class="footer">
            <p>Выдал: ___________________ / _______________</p>
            <p>Принял: ___________________ / _______________</p>
          </div>
        </body>
      </html>
    `;
    printWindow.document.write(html);
    printWindow.document.close();
  };

  return (
    <div className="flex h-screen bg-gray-100 font-sans">
      {/* Left Panel */}
      <div className="w-80 bg-white shadow-lg flex flex-col overflow-y-auto z-10">
        <div className="p-4 bg-slate-800 text-white">
          <h1 className="text-xl font-bold">Учет КИПиА</h1>
          <p className="text-xs text-slate-400">Web-версия (Preview)</p>
        </div>
        
        <div className="p-4 space-y-4 flex-1">
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-700">Цех (Ц47, Ц66...)</label>
              <input type="text" className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2" 
                value={formData.shop || ''} onChange={e => setFormData({...formData, shop: e.target.value})} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Название прибора</label>
              <input type="text" className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2" 
                value={formData.name || ''} onChange={e => setFormData({...formData, name: e.target.value})} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Модель/Зав.№</label>
              <input type="text" className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2" 
                value={formData.model || ''} onChange={e => setFormData({...formData, model: e.target.value})} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Шкала</label>
              <input type="text" className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2" 
                value={formData.scale || ''} onChange={e => setFormData({...formData, scale: e.target.value})} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Дата поверки (ДД.ММ.ГГГГ)</label>
              <input type="text" placeholder="01.01.2024" className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2" 
                value={formData.last_date || ''} onChange={e => setFormData({...formData, last_date: e.target.value})} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Интервал (мес)</label>
              <input type="number" className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2" 
                value={formData.interval_mo || ''} onChange={e => setFormData({...formData, interval_mo: Number(e.target.value)})} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Пометки</label>
              <input type="text" className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2" 
                value={formData.notes || ''} onChange={e => setFormData({...formData, notes: e.target.value})} />
            </div>
          </div>

          <div className="space-y-2 pt-4 border-t">
            <button onClick={handleSave} className="w-full flex justify-center items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700">
              <Save className="w-4 h-4 mr-2" /> Сохранить
            </button>
            <button onClick={handleClear} className="w-full flex justify-center items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50">
              Очистить форму
            </button>
            <button onClick={handleDelete} disabled={!formData.id} className="w-full flex justify-center items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-50">
              <Trash2 className="w-4 h-4 mr-2" /> Удалить
            </button>
          </div>
          
          <div className="pt-4 border-t">
             <button onClick={() => alert('В web-версии открытие локальных папок недоступно. Используйте Python .exe версию.')} className="w-full flex justify-center items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50">
              <Map className="w-4 h-4 mr-2" /> Схемы цехов
            </button>
          </div>
        </div>
      </div>

      {/* Right Panel */}
      <div className="flex-1 flex flex-col overflow-hidden p-6 gap-4">
        
        {/* Top Bar: Search and Print */}
        <div className="flex justify-between items-center bg-white p-3 rounded-lg shadow-sm">
          <div className="relative w-96">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-5 w-5 text-gray-400" />
            </div>
            <input
              type="text"
              className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md leading-5 bg-white placeholder-gray-500 focus:outline-none focus:placeholder-gray-400 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
              placeholder="Поиск по названию, модели или цеху..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <button onClick={() => handlePrint('ppr')} className="flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50">
              <Printer className="w-4 h-4 mr-2 text-gray-500" /> Печать ППР
            </button>
            <button onClick={() => handlePrint('task')} className="flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-slate-800 hover:bg-slate-900">
              <Printer className="w-4 h-4 mr-2" /> Сменное задание
            </button>
          </div>
        </div>

        {/* Table */}
        <div className="bg-white shadow rounded-lg flex-1 overflow-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50 sticky top-0 z-10">
              <tr>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">☑</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Цех</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Название</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Модель</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Шкала</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Дата пов.</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Инт.</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">След. пов.</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Пометки</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {filteredDevices.map((device) => (
                <tr 
                  key={device.id} 
                  className={`cursor-pointer transition-colors ${getRowColor(device)}`}
                  onClick={() => setFormData(device)}
                >
                  <td className="px-3 py-2 whitespace-nowrap" onClick={(e) => { e.stopPropagation(); toggleCheck(device.id); }}>
                    {checkedIds.has(device.id) ? <CheckSquare className="w-5 h-5 text-blue-600" /> : <Square className="w-5 h-5 text-gray-400" />}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm font-medium">{device.shop}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm">{device.name}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm">{device.model}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm">{device.scale}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm">{device.last_date}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm">{device.interval_mo}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm font-bold">{device.next_date}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm">{device.notes}</td>
                </tr>
              ))}
              {filteredDevices.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-6 py-10 text-center text-gray-500">
                    {devices.length === 0 ? 'Нет данных. Добавьте приборы через форму слева.' : 'По вашему запросу ничего не найдено.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        
        <div className="flex gap-4 text-sm text-gray-600 bg-white p-3 rounded-lg shadow-sm">
          <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-red-400 mr-2"></span> Просрочено</div>
          <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-yellow-400 mr-2"></span> &le; 30 дней</div>
          <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-blue-400 mr-2"></span> Спецсталь &le; 90 дней</div>
        </div>
      </div>
    </div>
  );
}

