from multiprocessing.pool import ThreadPool
from tqdm import tqdm
import requests
import pandas as pd
import xml.etree.ElementTree as ET
import calendar
import io



def definir_host(instituicao):
    mapping = {
        "ccee": "https://dadosabertos.ccee.org.br",
        "ons": "https://dados.ons.org.br",
        "aneel": "https://dadosabertos.aneel.gov.br"
    }
    host = mapping.get(instituicao.lower())

    return host

def listar_produtos(instituicao):

    if instituicao=='ana':
        return ['vazao', 'chuva', 'cota']

    else:
        host= definir_host(instituicao)
        try:
            r = requests.get(f"{host}/api/3/action/package_list")
            r.raise_for_status()
            return r.json().get("result", [])
        except Exception as e:
            print(f"Erro ao listar produtos: {e}")
            return []
        





def listar_estacoes_ana(produto=None, state='', city=''):
    
    if produto is None:
            raise ValueError("É necessário fornecer o nome do produto ('vazao', 'chuva' ou 'cota')")
    if produto== 'vazao':
        tipo= '1'
    elif produto=='chuva':
        tipo= '2'
    elif produto== 'cota':
        tipo= '3'

    url = 'http://telemetriaws1.ana.gov.br/ServiceANA.asmx/HidroInventario'
    
    params = {
        'codEstDE': '',
        'codEstATE': '',
        'tpEst': tipo,  # 1= fluviométrica
        'nmEst': '',
        'nmRio': '',
        'codSubBacia': '',
        'codBacia': '',
        'nmMunicipio': city,
        'nmEstado': state,
        'sgResp': '',
        'sgOper': '',
        'telemetrica': ''
    }
    
    response = requests.get(url, params=params, timeout=120)
    tree = ET.ElementTree(ET.fromstring(response.content))
    root = tree.getroot()
    
    stations = []
    for station in root.iter('Table'):
        stations.append({
            'Code': f'{int(station.find("Codigo").text):08}',
            'Name': station.find('Nome').text,
            'City': station.find('nmMunicipio').text,
            'State': station.find('nmEstado').text,
            'Latitude': float(station.find('Latitude').text),
            'Longitude': float(station.find('Longitude').text)
        })
    
    return pd.DataFrame(stations)
    





def dados_ana(list_station, data_type, threads=10):
        if type(list_station) is not list:
            list_station = [list_station]
        data_types = {'3': ['Vazao{:02}'], '2': ['Chuva{:02}'], '1': ['Cota{:02}']}

        def __call_request(station):
            params = {'codEstacao': str(station), 'dataInicio': '', 'dataFim': '', 'tipoDados': data_type, 'nivelConsistencia': ''}
            
            response = requests.get('http://telemetriaws1.ana.gov.br/ServiceANA.asmx/HidroSerieHistorica', params,
                                        timeout=120.0)

            tree = ET.ElementTree(ET.fromstring(response.content))
            root = tree.getroot()
            
            df = []
            for month in root.iter('SerieHistorica'):
                code = month.find('EstacaoCodigo').text
                code = f'{int(code):08}'
                consist = int(month.find('NivelConsistencia').text)
                date = pd.to_datetime(month.find('DataHora').text, dayfirst=False)
                date = pd.Timestamp(date.year, date.month, 1, 0)
                last_day = calendar.monthrange(date.year, date.month)[1]
                month_dates = pd.date_range(date, periods=last_day, freq='D')
                data = []
                list_consist = []
                for i in range(last_day):
                    value = data_types[params['tipoDados']][0].format(i + 1)
                    try:
                        data.append(float(month.find(value).text))
                        list_consist.append(consist)
                    except TypeError:
                        data.append(month.find(value).text)
                        list_consist.append(consist)
                    except AttributeError:
                        data.append(None)
                        list_consist.append(consist)
                index_multi = list(zip(month_dates, list_consist))
                index_multi = pd.MultiIndex.from_tuples(index_multi, names=["Date", "Consistence"])
                df.append(pd.DataFrame({code: data}, index=index_multi))
            if (len(df)) == 0:
                return pd.DataFrame()
            df = pd.concat(df)
            df = df.sort_index()
            
            drop_index = df.reset_index(level=1, drop=True).index.duplicated(keep='last')
            df = df[~drop_index]
            df = df.reset_index(level=1, drop=True)
            
            series = df[code]
            date_index = pd.date_range(series.index[0], series.index[-1], freq='D')
            series = series.reindex(date_index)
            return series

        if len(list_station) < threads:
            threads = len(list_station)

        with ThreadPool(threads) as pool:
            responses = list(tqdm(pool.imap(__call_request, list_station), total=len(list_station)))
        responses = [response for response in responses if not response.empty]
        data_stations = pd.concat(responses, axis=1)
        date_index = pd.date_range(data_stations.index[0], data_stations.index[-1], freq='D')
        data_stations = data_stations.reindex(date_index)

        inicio, fim = data_stations.first_valid_index(), data_stations.last_valid_index()
        data_stations= data_stations.loc[inicio:fim]

        return data_stations


# procura a url dos arquivos dentro de um produto
def buscar_arquivos(host, produto):
    r = requests.get(f"{host}/api/3/action/package_show?id={produto}")
    data = r.json()
    if data.get('success'):
        # Captura a URL e o formato (csv, zip, xlsx, etc)
        return [
            {"url": item['url'], "format": item.get('format', '').lower()} 
            for item in data['result']['resources']
        ]
    return []

# baixa um csv do produto
def baixar_arquivo_csv(url):
    try:
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
        df = pd.read_csv(io.BytesIO(resp.content), sep=";", encoding="latin-1", on_bad_lines="skip")
        return df
    except Exception as e:
        return pd.DataFrame()

# baixa todos os csv's de um produto e retorna um dataframe
def baixar_dados_produto(instituicao, produto):
    host = definir_host(instituicao)
    recursos = buscar_arquivos(host, produto)

    links_csv = [res["url"] for res in recursos if "csv" in res["format"]]
    if not links_csv:
        print(f"O produto '{produto}' não possui arquivos CSV.")
        return None
    
    print(f"Iniciando download de {len(links_csv)} arquivos...")
    dfs = [baixar_arquivo_csv(url) for url in links_csv]
    dfs_validos = [df for df in dfs if not df.empty]

    if dfs_validos:
        return pd.concat(dfs_validos, ignore_index=True)
    return None


def coletar_dados(instituicao, produto=None, estacoes=None):
    if instituicao.lower() == 'ana':
        if estacoes is None or produto is None:
            raise ValueError("É necessário fornecer o nome do produto ('vazao', 'chuva' ou 'cota') e das estações")
        if produto== 'vazao':
            tipo= '3'
        elif produto=='chuva':
            tipo= '2'
        elif produto== 'cota':
            tipo= '1'
        return dados_ana(estacoes, tipo)
    
    elif instituicao.lower() in ['ons','aneel','ccee']:
        if produto is None:
            raise ValueError('É necessário fornecer o nome do produto')
        return baixar_dados_produto(instituicao, produto)
    
    else:
        raise ValueError("Instituição inválida. Use 'ana', 'ons', 'aneel' ou 'ccee'")